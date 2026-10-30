// A robot's own hosted web page in a native window: what you see is the page it serves, so it can
// never drift from it. The window only adds finding the robot and remembering where it was.
//
//   NAME-Controller.exe                      the last address, or the one in robot.h
//   NAME-Controller.exe --host 192.168.4.1
//
//   F5   reload        F6   change the address
//
// Build with build.bat (Visual Studio 2022). The WebView2 runtime comes with Windows 11.
#include <windows.h>
#include <iphlpapi.h>
#include <shlobj.h>
#include <shellapi.h>
#include <winhttp.h>
#include <wrl.h>

#include <algorithm>
#include <cwctype>
#include <string>
#include <thread>
#include <vector>

#include "WebView2.h"
#include "robot.h"
#include "web_files.h"

#pragma comment(lib, "advapi32.lib")
#pragma comment(lib, "iphlpapi.lib")
#pragma comment(lib, "ole32.lib")
#pragma comment(lib, "shell32.lib")
#pragma comment(lib, "shlwapi.lib")
#pragma comment(lib, "user32.lib")
#pragma comment(lib, "version.lib")
#pragma comment(lib, "winhttp.lib")

using Microsoft::WRL::Callback;
using Microsoft::WRL::ComPtr;

static UINT foundMessage;      // registered: WebView2 uses the WM_APP range on this window itself
static const DWORD HTTP_TIMEOUT_MS = 1500;
static const DWORD PROBE_TIMEOUT_MS = 3000;

static HWND window;
static ComPtr<ICoreWebView2Controller> controller;
static ComPtr<ICoreWebView2> web;
static std::wstring host;
static bool showingConnect = false;

static std::wstring widen(const std::string &s)
{
    if (s.empty()) return L"";
    std::wstring out(MultiByteToWideChar(CP_UTF8, 0, s.data(), (int)s.size(), nullptr, 0), 0);
    MultiByteToWideChar(CP_UTF8, 0, s.data(), (int)s.size(), &out[0], (int)out.size());
    return out;
}

static std::string narrow(const std::wstring &s)
{
    if (s.empty()) return "";
    std::string out(WideCharToMultiByte(CP_UTF8, 0, s.data(), (int)s.size(), nullptr, 0, nullptr, nullptr), 0);
    WideCharToMultiByte(CP_UTF8, 0, s.data(), (int)s.size(), &out[0], (int)out.size(), nullptr, nullptr);
    return out;
}

static std::wstring appFolder(int where)
{
    wchar_t path[MAX_PATH];
    SHGetFolderPathW(nullptr, where, nullptr, 0, path);
    std::wstring folder = std::wstring(path) + L"\\DREAM Robotics";
    CreateDirectoryW(folder.c_str(), nullptr);
    folder += L"\\" + std::wstring(ROBOT_NAME);
    CreateDirectoryW(folder.c_str(), nullptr);
    return folder;
}

static std::wstring settingsFile() { return appFolder(CSIDL_APPDATA) + L"\\controller.ini"; }

static std::wstring loadHost()
{
    wchar_t value[128];
    GetPrivateProfileStringW(L"robot", L"host", ROBOT_HOST, value, 128, settingsFile().c_str());
    return value;
}

static void saveHost(const std::wstring &value)
{
    WritePrivateProfileStringW(L"robot", L"host", value.c_str(), settingsFile().c_str());
}

static std::wstring pageUrl()
{
    return L"http://" + host + L":" + std::to_wstring(ROBOT_PORT) + ROBOT_PATH;
}

static void setTitle(const std::wstring &where)
{
    SetWindowTextW(window, (std::wstring(ROBOT_NAME) + L" - " + where).c_str());
}

// ---- the page for when there's no robot yet: it fills in its {{...}} here ----
static std::string replaced(std::string text, const std::string &from, const std::string &to)
{
    for (size_t at = text.find(from); at != std::string::npos; at = text.find(from, at + to.size())) {
        text.replace(at, from.size(), to);
    }
    return text;
}

static std::string connectPage()
{
    std::string page = WEB_CONNECT_HTML;
    page = replaced(page, "{{CSS}}", WEB_CONNECT_CSS);
    page = replaced(page, "{{JS}}", WEB_CONNECT_JS);
    page = replaced(page, "{{BACKGROUND}}", ROBOT_BACKGROUND);
    page = replaced(page, "{{PANEL}}", ROBOT_PANEL);
    page = replaced(page, "{{BORDER}}", ROBOT_BORDER);
    page = replaced(page, "{{TEXT}}", ROBOT_TEXT);
    page = replaced(page, "{{ACCENT}}", ROBOT_ACCENT);
    page = replaced(page, "{{NAME}}", std::string(ROBOT_NAME_U8));
    return page;
}

static void showConnect(const std::wstring &note)
{
    showingConnect = true;
    setTitle(L"not connected");
    std::string page = connectPage();
    page = replaced(page, "{{HOST}}", narrow(host));
    page = replaced(page, "{{NOTE}}", narrow(note));
    web->NavigateToString(widen(page).c_str());
}

static UINT answerMessage;     // wparam: which try; lparam: did it answer
static unsigned probe = 0;
static bool answers(const std::wstring &server, int port, const std::wstring &path);

static void openRobot()
{
    if (host.empty()) {
        showConnect(L"Type the address, or press FIND");
        return;
    }
    // Ask first: with no route to it the browser sits on an empty window for 20 s or more
    showConnect(L"Connecting to " + host + L"...");
    const unsigned mine = ++probe;
    const std::wstring server = host;
    std::thread([mine, server] {
        PostMessageW(window, answerMessage, mine, answers(server, ROBOT_PORT, ROBOT_PATH));
    }).detach();
}

// ---- something on this PC: if its server isn't up, start it and keep trying for a minute ----
#ifdef ROBOT_START
static const int START_TRIES = 20;
static const UINT START_WAIT_MS = 3000;
static int startTries = -1;

static bool startingServer()
{
    if (host != L"127.0.0.1" || startTries == 0) return false;
    if (startTries < 0) {
        wchar_t exe[MAX_PATH];
        GetModuleFileNameW(nullptr, exe, MAX_PATH);
        std::wstring repo = exe;
        repo = repo.substr(0, repo.find_last_of(L'\\'));     // builds
        repo = repo.substr(0, repo.find_last_of(L'\\'));
        ShellExecuteW(nullptr, L"open", (repo + L"\\run.bat").c_str(), nullptr, repo.c_str(), SW_SHOWMINNOACTIVE);
        startTries = START_TRIES;
    }
    startTries--;
    showConnect(L"Starting " + std::wstring(ROBOT_NAME) + L" on this PC...");
    SetTimer(window, 1, START_WAIT_MS, nullptr);
    return true;
}
#else
static bool startingServer() { return false; }
#endif

// ---- FIND: the fleet list on whoever hosts this network, the same way the Android apps look ----
// Its headers are enough: an ESP32 can take seconds to send a whole page
static bool answers(const std::wstring &server, int port, const std::wstring &path)
{
    bool ok = false;
    HINTERNET session = WinHttpOpen(L"DREAM controller", WINHTTP_ACCESS_TYPE_NO_PROXY, nullptr, nullptr, 0);
    if (!session) return false;
    WinHttpSetTimeouts(session, PROBE_TIMEOUT_MS, PROBE_TIMEOUT_MS, PROBE_TIMEOUT_MS, PROBE_TIMEOUT_MS);
    HINTERNET connection = WinHttpConnect(session, server.c_str(), (INTERNET_PORT)port, 0);
    HINTERNET request = connection ? WinHttpOpenRequest(connection, L"GET", path.c_str(), nullptr, nullptr, nullptr, 0) : nullptr;
    if (request && WinHttpSendRequest(request, nullptr, 0, nullptr, 0, 0, 0)) {
        ok = WinHttpReceiveResponse(request, nullptr) != FALSE;
    }
    if (request) WinHttpCloseHandle(request);
    if (connection) WinHttpCloseHandle(connection);
    WinHttpCloseHandle(session);
    return ok;
}

static std::string httpGet(const std::wstring &server, int port, const std::wstring &path)
{
    std::string body;
    HINTERNET session = WinHttpOpen(L"DREAM controller", WINHTTP_ACCESS_TYPE_NO_PROXY, nullptr, nullptr, 0);
    if (!session) return body;
    WinHttpSetTimeouts(session, HTTP_TIMEOUT_MS, HTTP_TIMEOUT_MS, HTTP_TIMEOUT_MS, HTTP_TIMEOUT_MS);
    HINTERNET connection = WinHttpConnect(session, server.c_str(), (INTERNET_PORT)port, 0);
    HINTERNET request = connection ? WinHttpOpenRequest(connection, L"GET", path.c_str(), nullptr, nullptr, nullptr, 0) : nullptr;
    if (request && WinHttpSendRequest(request, nullptr, 0, nullptr, 0, 0, 0) && WinHttpReceiveResponse(request, nullptr)) {
        DWORD got = 0;
        char chunk[4096];
        while (WinHttpReadData(request, chunk, sizeof(chunk), &got) && got) {
            body.append(chunk, got);
        }
    }
    if (request) WinHttpCloseHandle(request);
    if (connection) WinHttpCloseHandle(connection);
    WinHttpCloseHandle(session);
    return body;
}

static std::vector<std::wstring> gateways()
{
    std::vector<std::wstring> found;
    ULONG size = 0;
    GetAdaptersInfo(nullptr, &size);
    std::vector<char> buffer(size);
    auto *adapter = reinterpret_cast<IP_ADAPTER_INFO *>(buffer.data());
    if (size && GetAdaptersInfo(adapter, &size) == NO_ERROR) {
        for (; adapter; adapter = adapter->Next) {
            const std::string gateway = adapter->GatewayList.IpAddress.String;
            if (!gateway.empty() && gateway != "0.0.0.0") {
                found.push_back(widen(gateway));
            }
        }
    }
    return found;
}

static std::string plainName(std::string name)
{
    name.erase(std::remove(name.begin(), name.end(), '-'), name.end());
    std::transform(name.begin(), name.end(), name.begin(), [](unsigned char c) { return (char)toupper(c); });
    return name;
}

static std::string jsonString(const std::string &object, const std::string &key)
{
    const size_t at = object.find("\"" + key + "\"");
    const size_t colon = at == std::string::npos ? at : object.find(':', at);
    const size_t open = colon == std::string::npos ? colon : object.find('"', colon);
    const size_t close = open == std::string::npos ? open : object.find('"', open + 1);
    return close == std::string::npos ? "" : object.substr(open + 1, close - open - 1);
}

static std::string robotIn(const std::string &list)
{
    const std::string wanted = plainName(ROBOT_FLEET_NAME);
    for (size_t open = list.find('{', 1); open != std::string::npos; open = list.find('{', open + 1)) {
        const size_t close = list.find('}', open);
        if (close == std::string::npos) break;
        const std::string object = list.substr(open, close - open);
        if (plainName(jsonString(object, "name")) == wanted) {
            return jsonString(object, "ip");
        }
    }
    return "";
}

static void find()
{
    std::thread([] {
        std::string ip;
#ifdef ROBOT_START
        if (!httpGet(L"127.0.0.1", ROBOT_PORT, ROBOT_PATH).empty()) ip = "127.0.0.1";   // it runs on this PC
#endif
        for (const std::wstring &gateway : ip.empty() ? gateways() : std::vector<std::wstring>()) {
            std::string list = httpGet(gateway, 5000, L"/fleet");
            if (list.empty()) list = httpGet(gateway, 5000, L"/robots");
            ip = robotIn(list);
            if (!ip.empty()) break;
        }
        PostMessageW(window, foundMessage, 0, (LPARAM) new std::wstring(widen(ip)));
    }).detach();
}

// ---- the window ----
static void fit()
{
    if (!controller) return;
    RECT bounds;
    GetClientRect(window, &bounds);
    controller->put_Bounds(bounds);
}

static void messageFromPage(const std::wstring &text)
{
    if (text == L"find") {
        find();
    } else if (text.rfind(L"go:", 0) == 0) {
        host = text.substr(3);
        saveHost(host);
        openRobot();
    }
}

static void startPage()
{
    web->add_NavigationCompleted(
        Callback<ICoreWebView2NavigationCompletedEventHandler>(
            [](ICoreWebView2 *, ICoreWebView2NavigationCompletedEventArgs *args) -> HRESULT {
                BOOL ok = FALSE;
                args->get_IsSuccess(&ok);
                if (!ok && !showingConnect && !startingServer()) showConnect(L"No answer from " + host);
                return S_OK;
            }).Get(), nullptr);
    web->add_WebMessageReceived(
        Callback<ICoreWebView2WebMessageReceivedEventHandler>(
            [](ICoreWebView2 *, ICoreWebView2WebMessageReceivedEventArgs *args) -> HRESULT {
                LPWSTR text = nullptr;
                if (SUCCEEDED(args->TryGetWebMessageAsString(&text))) {
                    messageFromPage(text);
                    CoTaskMemFree(text);
                }
                return S_OK;
            }).Get(), nullptr);
    controller->add_AcceleratorKeyPressed(
        Callback<ICoreWebView2AcceleratorKeyPressedEventHandler>(
            [](ICoreWebView2Controller *, ICoreWebView2AcceleratorKeyPressedEventArgs *args) -> HRESULT {
                UINT key = 0;
                COREWEBVIEW2_KEY_EVENT_KIND kind;
                args->get_VirtualKey(&key);
                args->get_KeyEventKind(&kind);
                if (kind == COREWEBVIEW2_KEY_EVENT_KIND_KEY_DOWN && key == VK_F6) {
                    args->put_Handled(TRUE);
                    showConnect(L"Change the address");
                }
                return S_OK;
            }).Get(), nullptr);
    openRobot();
}

static void startWebView()
{
    const std::wstring data = appFolder(CSIDL_LOCAL_APPDATA);
    const HRESULT started = CreateCoreWebView2EnvironmentWithOptions(
        nullptr, data.c_str(), nullptr,
        Callback<ICoreWebView2CreateCoreWebView2EnvironmentCompletedHandler>(
            [](HRESULT result, ICoreWebView2Environment *environment) -> HRESULT {
                if (FAILED(result)) {
                    MessageBoxW(window, L"Windows' WebView2 runtime didn't start.", ROBOT_NAME, MB_ICONERROR);
                    return result;
                }
                return environment->CreateCoreWebView2Controller(
                    window,
                    Callback<ICoreWebView2CreateCoreWebView2ControllerCompletedHandler>(
                        [](HRESULT made, ICoreWebView2Controller *created) -> HRESULT {
                            if (FAILED(made)) return made;
                            controller = created;
                            controller->get_CoreWebView2(&web);
                            fit();
                            startPage();
                            return S_OK;
                        }).Get());
            }).Get());
    if (FAILED(started)) {
        MessageBoxW(window, L"This needs Microsoft's WebView2 runtime, which comes with Windows 11.", ROBOT_NAME, MB_ICONERROR);
        PostQuitMessage(1);
    }
}

static LRESULT CALLBACK windowProc(HWND hwnd, UINT message, WPARAM wparam, LPARAM lparam)
{
    if (message == answerMessage) {
        if ((unsigned)wparam != probe) return 0;      // an older try, for an address since changed
        if (lparam) {
            showingConnect = false;
            setTitle(host);
            web->Navigate(pageUrl().c_str());
        } else if (!startingServer()) {
            showConnect(L"No answer from " + host);
        }
        return 0;
    }
    if (message == foundMessage) {
        std::wstring *ip = reinterpret_cast<std::wstring *>(lparam);
        if (ip->empty()) {
            showConnect(L"Not on the fleet list of this network");
        } else {
            host = *ip;
            saveHost(host);
            openRobot();
        }
        delete ip;
        return 0;
    }
    switch (message) {
    case WM_TIMER:
        KillTimer(hwnd, wparam);
        openRobot();
        return 0;
    case WM_SIZE:
        fit();
        return 0;
    case WM_DESTROY:
        PostQuitMessage(0);
        return 0;
    }
    return DefWindowProcW(hwnd, message, wparam, lparam);
}

int WINAPI wWinMain(HINSTANCE instance, HINSTANCE, PWSTR, int show)
{
    CoInitializeEx(nullptr, COINIT_APARTMENTTHREADED);
    foundMessage = RegisterWindowMessageW(L"DreamControllerFound");
    answerMessage = RegisterWindowMessageW(L"DreamControllerAnswer");
    host = loadHost();
    int argc = 0;
    LPWSTR *argv = CommandLineToArgvW(GetCommandLineW(), &argc);
    for (int i = 1; i + 1 < argc; i++) {
        if (wcscmp(argv[i], L"--host") == 0) host = argv[i + 1];
    }
    LocalFree(argv);

    WNDCLASSW type = {};
    type.lpfnWndProc = windowProc;
    type.hInstance = instance;
    type.hIcon = LoadIconW(instance, MAKEINTRESOURCEW(1));
    type.hCursor = LoadCursor(nullptr, IDC_ARROW);
    type.lpszClassName = L"DreamController";
    RegisterClassW(&type);
    window = CreateWindowW(type.lpszClassName, ROBOT_NAME, WS_OVERLAPPEDWINDOW, CW_USEDEFAULT, CW_USEDEFAULT,
                           ROBOT_WIDTH, ROBOT_HEIGHT, nullptr, nullptr, instance, nullptr);
    ShowWindow(window, show);
    startWebView();

    MSG message;
    while (GetMessageW(&message, nullptr, 0, 0)) {
        TranslateMessage(&message);
        DispatchMessageW(&message);
    }
    return 0;
}
