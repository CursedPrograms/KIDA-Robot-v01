// image.h — decode JPEGs (camera frames, last photo, character face) with
// Windows Imaging Component into 32-bit BGRA pixels GDI can draw.
#pragma once

#define WIN32_LEAN_AND_MEAN
#include <windows.h>
#include <wincodec.h>

#include <memory>
#include <string>
#include <vector>

struct Image {
    int w = 0, h = 0;
    std::vector<unsigned char> bgra;   // w * h * 4, top-down
    bool empty() const { return w == 0 || h == 0; }
};

using ImagePtr = std::shared_ptr<const Image>;

// Call once per thread that decodes (COM must be initialised on it).
struct ComScope {
    ComScope() { CoInitializeEx(nullptr, COINIT_MULTITHREADED); }
    ~ComScope() { CoUninitialize(); }
};

inline ImagePtr decodeImage(const unsigned char* data, size_t len) {
    if (!data || len < 4) return nullptr;
    IWICImagingFactory* factory = nullptr;
    if (FAILED(CoCreateInstance(CLSID_WICImagingFactory, nullptr, CLSCTX_INPROC_SERVER,
                                IID_PPV_ARGS(&factory))))
        return nullptr;
    ImagePtr result;
    IWICStream* stream = nullptr;
    IWICBitmapDecoder* decoder = nullptr;
    IWICBitmapFrameDecode* frame = nullptr;
    IWICFormatConverter* conv = nullptr;
    if (SUCCEEDED(factory->CreateStream(&stream))
        && SUCCEEDED(stream->InitializeFromMemory(const_cast<BYTE*>(data), (DWORD)len))
        && SUCCEEDED(factory->CreateDecoderFromStream(stream, nullptr, WICDecodeMetadataCacheOnDemand, &decoder))
        && SUCCEEDED(decoder->GetFrame(0, &frame))
        && SUCCEEDED(factory->CreateFormatConverter(&conv))
        && SUCCEEDED(conv->Initialize(frame, GUID_WICPixelFormat32bppBGRA, WICBitmapDitherTypeNone,
                                      nullptr, 0.0, WICBitmapPaletteTypeCustom))) {
        UINT w = 0, h = 0;
        conv->GetSize(&w, &h);
        auto img = std::make_shared<Image>();
        img->w = (int)w;
        img->h = (int)h;
        img->bgra.resize((size_t)w * h * 4);
        if (SUCCEEDED(conv->CopyPixels(nullptr, w * 4, (UINT)img->bgra.size(), img->bgra.data())))
            result = img;
    }
    if (conv) conv->Release();
    if (frame) frame->Release();
    if (decoder) decoder->Release();
    if (stream) stream->Release();
    factory->Release();
    return result;
}

inline ImagePtr decodeImage(const std::string& bytes) {
    return decodeImage(reinterpret_cast<const unsigned char*>(bytes.data()), bytes.size());
}

inline ImagePtr decodeImage(const std::vector<unsigned char>& bytes) {
    return decodeImage(bytes.data(), bytes.size());
}
