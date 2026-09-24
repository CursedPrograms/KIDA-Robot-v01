// robot.h — everything the controller knows about the robot, kept fresh by
// background threads (the C++ twin of controller/scripts/remote_client.py):
//
//   status    GET /status every 0.5 s (mode, sensors, power, lock, scheme, rumble...)
//   mind      GET /mind every 5 s (her mood; the panel just hides if there's no mind)
//   cameras   /video_feed/0 and /video_feed/1, MJPEG, decoded as they arrive
//   images    /character_face once, /last_photo whenever last_photo_ts changes
//   actions   POST /action from one worker thread, so the UI never waits on the
//             network. Drive heartbeats coalesce: a newer joy_drive replaces an
//             older one still waiting, so a slow link can't build up a backlog
//             of stale steering.
#pragma once

#include <atomic>
#include <condition_variable>
#include <deque>
#include <functional>
#include <mutex>
#include <string>
#include <thread>

#include "image.h"
#include "json.h"
#include "net.h"

struct Action {
    std::string body;        // full JSON body
    std::string coalesce;    // "" = never replaced; else a newer one with the same key replaces it
    std::function<void(bool ok)> done;   // optional, called on the worker thread
};

class Robot {
public:
    Robot(const std::string& host, int port) : host_(host), port_(port) {}
    ~Robot() { stop(); }

    void start() {
        threads_.emplace_back([this] { statusLoop(); });
        threads_.emplace_back([this] { mindLoop(); });
        threads_.emplace_back([this] { camLoop(0); });
        threads_.emplace_back([this] { camLoop(1); });
        threads_.emplace_back([this] { actionLoop(); });
    }

    void stop() {
        if (stop_.exchange(true)) return;
        cv_.notify_all();
        for (auto& t : threads_) if (t.joinable()) t.join();
        threads_.clear();
    }

    // ── what the UI reads (copies, so no lock is held while drawing) ──
    JValue status() { std::lock_guard<std::mutex> g(m_); return status_; }
    JValue mind() { std::lock_guard<std::mutex> g(m_); return mind_; }
    ImagePtr frame(int cam) { std::lock_guard<std::mutex> g(m_); return cam ? frame1_ : frame0_; }
    ImagePtr face() { std::lock_guard<std::mutex> g(m_); return face_; }
    ImagePtr lastPhoto() { std::lock_guard<std::mutex> g(m_); return photo_; }
    bool connected() const { return connected_; }
    std::string address() const { return host_ + ":" + std::to_string(port_); }

    // ── commands ──
    void send(const std::string& command, const std::string& extraFields = "",
              const std::string& coalesce = "", std::function<void(bool)> done = nullptr) {
        std::string body = "{\"command\":" + jsonQuote(command);
        if (!extraFields.empty()) body += "," + extraFields;
        body += "}";
        std::lock_guard<std::mutex> g(qm_);
        if (!coalesce.empty()) {
            for (auto& a : queue_) {
                if (a.coalesce == coalesce) { a.body = body; a.done = done; cv_.notify_one(); return; }
            }
        }
        queue_.push_back({body, coalesce, done});
        cv_.notify_one();
    }

private:
    std::string host_;
    int port_;
    std::atomic<bool> stop_{false};
    std::atomic<bool> connected_{false};
    std::vector<std::thread> threads_;

    std::mutex m_;
    JValue status_, mind_;
    ImagePtr frame0_, frame1_, face_, photo_;
    std::string photoTsSeen_;

    std::mutex qm_;
    std::condition_variable cv_;
    std::deque<Action> queue_;

    void sleepFor(int ms) {
        for (int t = 0; t < ms && !stop_; t += 50) Sleep(50);
    }

    void statusLoop() {
        ComScope com;
        Http http(host_, port_);
        while (!stop_) {
            HttpResult r = http.get("/status", 1500);
            JValue s;
            if (r.ok() && parseJson(r.body, s)) {
                connected_ = true;
                { std::lock_guard<std::mutex> g(m_); status_ = s; }
                fetchImages(http, s);
            } else {
                connected_ = false;
            }
            sleepFor(500);
        }
    }

    void fetchImages(Http& http, const JValue& s) {
        bool needFace;
        { std::lock_guard<std::mutex> g(m_); needFace = !face_; }
        if (needFace) {
            HttpResult r = http.get("/character_face", 3000);
            if (r.ok()) if (auto img = decodeImage(r.body)) { std::lock_guard<std::mutex> g(m_); face_ = img; }
        }
        std::string ts = s["last_photo_ts"].text("");
        if (ts != photoTsSeen_) {
            photoTsSeen_ = ts;
            ImagePtr img;
            if (!ts.empty()) {
                HttpResult r = http.get("/last_photo?t=" + ts, 3000);
                if (r.ok()) img = decodeImage(r.body);
            }
            std::lock_guard<std::mutex> g(m_);
            photo_ = img;
        }
    }

    void mindLoop() {
        Http http(host_, port_);
        while (!stop_) {
            HttpResult r = http.get("/mind", 2000);
            JValue j;
            if (!(r.ok() && parseJson(r.body, j))) j = JValue();   // no mind running: panel hides
            { std::lock_guard<std::mutex> g(m_); mind_ = j; }
            sleepFor(5000);
        }
    }

    void camLoop(int cam) {
        ComScope com;
        Http http(host_, port_);
        std::string path = "/video_feed/" + std::to_string(cam);
        while (!stop_) {
            http.streamJpegs(path, stop_, [&](const std::vector<unsigned char>& jpg) {
                if (auto img = decodeImage(jpg)) {
                    std::lock_guard<std::mutex> g(m_);
                    (cam ? frame1_ : frame0_) = img;
                }
            });
            { std::lock_guard<std::mutex> g(m_); (cam ? frame1_ : frame0_) = nullptr; }   // stream dropped: NO SIGNAL
            sleepFor(1000);
        }
    }

    void actionLoop() {
        Http http(host_, port_);
        while (true) {
            Action a;
            {
                std::unique_lock<std::mutex> lk(qm_);
                cv_.wait(lk, [&] { return stop_ || !queue_.empty(); });
                if (queue_.empty()) return;          // stopping, nothing left to send
                a = std::move(queue_.front());
                queue_.pop_front();
            }
            HttpResult r = http.postJson("/action", a.body, 2000);
            bool ok = false;
            JValue j;
            if (r.ok() && parseJson(r.body, j)) ok = j["ok"].truthy();
            if (a.done) a.done(ok);
        }
    }
};
