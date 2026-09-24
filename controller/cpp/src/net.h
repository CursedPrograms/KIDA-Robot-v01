// net.h — talking to the robot's Flask server (scripts/server.py) over
// WinHTTP: GET (status, images), POST /action (JSON), and reading the MJPEG
// camera streams. The C++ twin of controller/scripts/remote_client.py.
#pragma once

#define WIN32_LEAN_AND_MEAN
#include <windows.h>
#include <winhttp.h>

#include <atomic>
#include <functional>
#include <string>
#include <vector>

inline std::wstring widen(const std::string& s) {
    if (s.empty()) return L"";
    int n = MultiByteToWideChar(CP_UTF8, 0, s.data(), (int)s.size(), nullptr, 0);
    std::wstring w(n, L'\0');
    MultiByteToWideChar(CP_UTF8, 0, s.data(), (int)s.size(), &w[0], n);
    return w;
}

inline std::string narrow(const std::wstring& w) {
    if (w.empty()) return "";
    int n = WideCharToMultiByte(CP_UTF8, 0, w.data(), (int)w.size(), nullptr, 0, nullptr, nullptr);
    std::string s(n, '\0');
    WideCharToMultiByte(CP_UTF8, 0, w.data(), (int)w.size(), &s[0], n, nullptr, nullptr);
    return s;
}

struct HttpResult {
    int status = 0;             // 0 = couldn't reach the robot
    std::string body;
    bool ok() const { return status >= 200 && status < 300; }
};

class Http {
public:
    // host: "192.168.1.50", port: 5004
    Http(const std::string& host, int port) : host_(widen(host)), port_((INTERNET_PORT)port) {
        session_ = WinHttpOpen(L"KIDA-Controller/1.0", WINHTTP_ACCESS_TYPE_NO_PROXY,
                               WINHTTP_NO_PROXY_NAME, WINHTTP_NO_PROXY_BYPASS, 0);
    }
    ~Http() { if (session_) WinHttpCloseHandle(session_); }
    Http(const Http&) = delete;
    Http& operator=(const Http&) = delete;

    HttpResult get(const std::string& path, int timeoutMs = 2000) {
        return request(L"GET", path, nullptr, timeoutMs);
    }

    HttpResult postJson(const std::string& path, const std::string& json, int timeoutMs = 2000) {
        return request(L"POST", path, &json, timeoutMs);
    }

    // Read an MJPEG stream until `stop` is set or the connection drops,
    // calling onJpeg(bytes) for every complete JPEG (FFD8 ... FFD9).
    void streamJpegs(const std::string& path, const std::atomic<bool>& stop,
                     const std::function<void(const std::vector<unsigned char>&)>& onJpeg) {
        HINTERNET conn = nullptr, req = nullptr;
        if (!open(L"GET", path, 5000, 5000, conn, req)) return;
        if (WinHttpSendRequest(req, WINHTTP_NO_ADDITIONAL_HEADERS, 0, WINHTTP_NO_REQUEST_DATA, 0, 0, 0)
            && WinHttpReceiveResponse(req, nullptr)) {
            std::vector<unsigned char> buf;
            std::vector<unsigned char> chunk(16384);
            while (!stop) {
                DWORD got = 0;
                if (!WinHttpReadData(req, chunk.data(), (DWORD)chunk.size(), &got) || got == 0) break;
                buf.insert(buf.end(), chunk.begin(), chunk.begin() + got);
                for (;;) {
                    size_t start = find(buf, 0xD8, 0);
                    if (start == npos) { if (buf.size() > 4) buf.erase(buf.begin(), buf.end() - 1); break; }
                    size_t end = find(buf, 0xD9, start + 2);
                    if (end == npos) {
                        if (start > 0) buf.erase(buf.begin(), buf.begin() + start);
                        if (buf.size() > 8 * 1024 * 1024) buf.clear();   // runaway: resync
                        break;
                    }
                    std::vector<unsigned char> jpg(buf.begin() + start, buf.begin() + end + 2);
                    buf.erase(buf.begin(), buf.begin() + end + 2);
                    onJpeg(jpg);
                }
            }
        }
        WinHttpCloseHandle(req);
        WinHttpCloseHandle(conn);
    }

private:
    std::wstring host_;
    INTERNET_PORT port_;
    HINTERNET session_ = nullptr;
    static constexpr size_t npos = (size_t)-1;

    // index of the 0xFF 0x<marker> pair at or after `from`
    static size_t find(const std::vector<unsigned char>& b, unsigned char marker, size_t from) {
        for (size_t i = from; i + 1 < b.size(); ++i)
            if (b[i] == 0xFF && b[i + 1] == marker) return i;
        return npos;
    }

    bool open(const wchar_t* verb, const std::string& path, int connectMs, int recvMs,
              HINTERNET& conn, HINTERNET& req) {
        if (!session_) return false;
        conn = WinHttpConnect(session_, host_.c_str(), port_, 0);
        if (!conn) return false;
        req = WinHttpOpenRequest(conn, verb, widen(path).c_str(), nullptr, WINHTTP_NO_REFERER,
                                 WINHTTP_DEFAULT_ACCEPT_TYPES, 0);
        if (!req) { WinHttpCloseHandle(conn); conn = nullptr; return false; }
        WinHttpSetTimeouts(req, connectMs, connectMs, connectMs, recvMs);
        return true;
    }

    HttpResult request(const wchar_t* verb, const std::string& path, const std::string* json, int timeoutMs) {
        HttpResult r;
        HINTERNET conn = nullptr, req = nullptr;
        if (!open(verb, path, timeoutMs, timeoutMs, conn, req)) return r;
        const wchar_t* headers = json ? L"Content-Type: application/json\r\n" : WINHTTP_NO_ADDITIONAL_HEADERS;
        DWORD hlen = json ? (DWORD)-1L : 0;
        void* data = json ? (void*)json->data() : WINHTTP_NO_REQUEST_DATA;
        DWORD dlen = json ? (DWORD)json->size() : 0;
        if (WinHttpSendRequest(req, headers, hlen, data, dlen, dlen, 0) && WinHttpReceiveResponse(req, nullptr)) {
            DWORD code = 0, sz = sizeof code;
            WinHttpQueryHeaders(req, WINHTTP_QUERY_STATUS_CODE | WINHTTP_QUERY_FLAG_NUMBER,
                                WINHTTP_HEADER_NAME_BY_INDEX, &code, &sz, WINHTTP_NO_HEADER_INDEX);
            r.status = (int)code;
            char chunk[8192];
            DWORD got = 0;
            while (WinHttpReadData(req, chunk, sizeof chunk, &got) && got > 0) r.body.append(chunk, got);
        }
        WinHttpCloseHandle(req);
        WinHttpCloseHandle(conn);
        return r;
    }
};
