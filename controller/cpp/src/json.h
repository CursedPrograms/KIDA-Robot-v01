// json.h — a small JSON reader for the robot's /status, /mind and /action
// replies. Parse-only (the controller builds its outgoing JSON by hand),
// tolerant of anything the Flask server sends: objects, arrays, strings,
// numbers, true/false/null.
#pragma once

#include <cstdio>
#include <cstdlib>
#include <map>
#include <memory>
#include <string>
#include <vector>

struct JValue {
    enum Type { Null, Bool, Number, String, Array, Object } type = Null;
    bool b = false;
    double n = 0.0;
    std::string s;
    std::vector<JValue> arr;
    std::map<std::string, JValue> obj;

    bool isNull() const { return type == Null; }

    const JValue& operator[](const std::string& key) const {
        static const JValue none;
        if (type != Object) return none;
        auto it = obj.find(key);
        return it == obj.end() ? none : it->second;
    }

    double num(double fallback = 0.0) const {
        if (type == Number) return n;
        if (type == Bool) return b ? 1.0 : 0.0;
        if (type == String) {
            char* end = nullptr;
            double v = std::strtod(s.c_str(), &end);
            if (end && end != s.c_str()) return v;
        }
        return fallback;
    }

    bool truthy() const {
        switch (type) {
            case Bool: return b;
            case Number: return n != 0.0;
            case String: return !s.empty();
            default: return false;
        }
    }

    // Anything as display text: "12.5", "ON", "—" for null.
    std::string text(const char* ifNull = "-") const {
        switch (type) {
            case Null: return ifNull;
            case Bool: return b ? "true" : "false";
            case String: return s;
            case Number: {
                char buf[64];
                if (n == (long long)n) std::snprintf(buf, sizeof buf, "%lld", (long long)n);
                else std::snprintf(buf, sizeof buf, "%.3g", n);
                return buf;
            }
            default: return "...";
        }
    }
};

class JsonParser {
public:
    explicit JsonParser(const std::string& src) : s_(src) {}

    bool parse(JValue& out) {
        pos_ = 0;
        ws();
        if (!value(out)) return false;
        ws();
        return true;
    }

private:
    const std::string& s_;
    size_t pos_ = 0;

    void ws() { while (pos_ < s_.size() && (s_[pos_] == ' ' || s_[pos_] == '\n' || s_[pos_] == '\r' || s_[pos_] == '\t')) ++pos_; }
    bool eat(char c) { ws(); if (pos_ < s_.size() && s_[pos_] == c) { ++pos_; return true; } return false; }
    bool lit(const char* w) {
        size_t n = std::char_traits<char>::length(w);
        if (s_.compare(pos_, n, w) == 0) { pos_ += n; return true; }
        return false;
    }

    static void utf8(std::string& o, unsigned cp) {
        if (cp < 0x80) o += (char)cp;
        else if (cp < 0x800) { o += (char)(0xC0 | (cp >> 6)); o += (char)(0x80 | (cp & 0x3F)); }
        else if (cp < 0x10000) { o += (char)(0xE0 | (cp >> 12)); o += (char)(0x80 | ((cp >> 6) & 0x3F)); o += (char)(0x80 | (cp & 0x3F)); }
        else { o += (char)(0xF0 | (cp >> 18)); o += (char)(0x80 | ((cp >> 12) & 0x3F)); o += (char)(0x80 | ((cp >> 6) & 0x3F)); o += (char)(0x80 | (cp & 0x3F)); }
    }

    bool str(std::string& o) {
        if (pos_ >= s_.size() || s_[pos_] != '"') return false;
        ++pos_;
        while (pos_ < s_.size()) {
            char c = s_[pos_++];
            if (c == '"') return true;
            if (c != '\\') { o += c; continue; }
            if (pos_ >= s_.size()) return false;
            char e = s_[pos_++];
            switch (e) {
                case 'n': o += '\n'; break;
                case 't': o += '\t'; break;
                case 'r': o += '\r'; break;
                case 'b': o += '\b'; break;
                case 'f': o += '\f'; break;
                case 'u': {
                    if (pos_ + 4 > s_.size()) return false;
                    unsigned cp = (unsigned)std::strtoul(s_.substr(pos_, 4).c_str(), nullptr, 16);
                    pos_ += 4;
                    if (cp >= 0xD800 && cp <= 0xDBFF && pos_ + 6 <= s_.size() && s_[pos_] == '\\' && s_[pos_ + 1] == 'u') {
                        unsigned lo = (unsigned)std::strtoul(s_.substr(pos_ + 2, 4).c_str(), nullptr, 16);
                        pos_ += 6;
                        cp = 0x10000 + ((cp - 0xD800) << 10) + (lo - 0xDC00);
                    }
                    utf8(o, cp);
                    break;
                }
                default: o += e;
            }
        }
        return false;
    }

    bool value(JValue& v) {
        ws();
        if (pos_ >= s_.size()) return false;
        char c = s_[pos_];
        if (c == '{') {
            ++pos_;
            v.type = JValue::Object;
            if (eat('}')) return true;
            do {
                ws();
                std::string key;
                if (!str(key) || !eat(':')) return false;
                JValue child;
                if (!value(child)) return false;
                v.obj[key] = std::move(child);
            } while (eat(','));
            return eat('}');
        }
        if (c == '[') {
            ++pos_;
            v.type = JValue::Array;
            if (eat(']')) return true;
            do {
                JValue child;
                if (!value(child)) return false;
                v.arr.push_back(std::move(child));
            } while (eat(','));
            return eat(']');
        }
        if (c == '"') { v.type = JValue::String; return str(v.s); }
        if (lit("true")) { v.type = JValue::Bool; v.b = true; return true; }
        if (lit("false")) { v.type = JValue::Bool; v.b = false; return true; }
        if (lit("null")) { v.type = JValue::Null; return true; }
        if (lit("NaN")) { v.type = JValue::Number; v.n = 0; return true; }
        char* end = nullptr;
        double d = std::strtod(s_.c_str() + pos_, &end);
        if (!end || end == s_.c_str() + pos_) return false;
        pos_ = (size_t)(end - s_.c_str());
        v.type = JValue::Number;
        v.n = d;
        return true;
    }
};

inline bool parseJson(const std::string& text, JValue& out) {
    JsonParser p(text);
    return p.parse(out);
}

// A string as a JSON string literal (for building request bodies).
inline std::string jsonQuote(const std::string& in) {
    std::string o = "\"";
    for (unsigned char c : in) {
        switch (c) {
            case '"': o += "\\\""; break;
            case '\\': o += "\\\\"; break;
            case '\n': o += "\\n"; break;
            case '\r': o += "\\r"; break;
            case '\t': o += "\\t"; break;
            default:
                if (c < 0x20) { char b[8]; std::snprintf(b, sizeof b, "\\u%04x", c); o += b; }
                else o += (char)c;
        }
    }
    return o + "\"";
}
