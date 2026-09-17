# RPI360

**先拍攝，再決定視角。**

RPI360 將雙魚眼相機的拍攝工作留在 Raspberry Pi，讓手機、平板或電腦負責
拼接、VR 視角、FOV、關鍵影格與影片匯出。Web 工作台可獨立運作，Mac worker
只是選用的原生匯出工具。

![湖畔視角重構](demos/posters/keyframe-reframing.jpg)

目前為 **v2 alpha**。已實作跨平台核心、相機服務與 Web 編輯流程，但不以
短時間測試宣稱通過長時間錄影或 Apple 實機驗收。詳見[驗證紀錄](docs/validation/status.md)。

## 不接相機也能試用

安裝 Rust、Node.js 22+ 與 pnpm 後：

```sh
pnpm install
rustup target add wasm32-unknown-unknown
cargo install wasm-bindgen-cli --version 0.2.108 --locked
pnpm wasm
pnpm dev
```

開啟終端機顯示的網址。內附三組由原片選出的魚眼影格，可以拖曳視角、調整
FOV、加入關鍵影格並直接在裝置上匯出 MP4。這些互動範例清楚標示為
「360 靜態影格重構」。

## 使用流程

1. 相機服務同步拍攝兩路魚眼，保存真實時間戳與校正快照。
2. 透過配對 API 將素材續傳至後置裝置，完成 checksum 驗證。
3. 在 Web 工作台中拼接、重構畫面、編輯關鍵影格並本機匯出。

預覽串流是成對並排的未拼接魚眼影像。FOV 與 orientation 全部由後置端
處理，操作視角不需要重新編碼或重新協商串流。

[Demo 與 recipes](demos/README.md) · [Web 快速開始](docs/getting-started/web.md) ·
[相機設定](docs/getting-started/camera.md) · [架構](docs/architecture.md) ·
[舊資料遷移](docs/migration/v2.md) · [英文完整說明](README.md)

原始戶外影片約為 5.6–6 fps，且有不規則掉幀。30 fps 輸出代表虛擬運鏡的
更新速度，不表示補出了原片沒有的動態細節。本版不包含 AI 追蹤、IMU 防震、
AI 補幀或雲端處理。
