# 🎙 VoiceInput

> 免安裝的語音轉文字輸入工具｜支援 Mac & Windows  
> 中英文混合辨識，智慧後處理，貼入任意應用程式

---

## ✨ 功能特色

- **按住**右 Command（Mac）/ 右 Ctrl（Windows）即時錄音，**放開**自動貼入
- **本地辨識為預設**：使用 mlx-whisper 在 Apple Silicon 上 GPU 加速，語音辨識無需上傳雲端
- 也可切換為 OpenAI Whisper API 雲端辨識，支援**中英混合語音**，自動判別語言
- 使用 Claude / GPT 做智慧後處理：移除「嗯」「那個」等語助詞，整理句子通順
- **自訂字典**：指定人名、專有名詞的正確寫法，辨識與後處理自動套用
- 貼入**任意應用程式**：Slack、LINE、Word、瀏覽器、Terminal 等
- 設定儲存在本機，API Key 不上傳
- 打包後**免安裝**，雙擊執行

---

## 🗂 檔案說明

```
voiceinput/
├── voice_input.py   ← 主程式
├── requirements.txt ← Python 依賴
├── build.py         ← 打包腳本
└── README.md        ← 本文件
```

---

## 🚀 快速開始

### 方式 A：直接用 Python 執行（開發模式）

**步驟 1｜安裝 Python 3.10+**  
https://www.python.org/downloads/

**步驟 2｜安裝依賴**

```bash
pip install -r requirements.txt
```

> macOS 若遇到 sounddevice 問題，可能需要先安裝 PortAudio：
> ```bash
> brew install portaudio
> pip install sounddevice
> ```

**步驟 3｜執行**

```bash
python voice_input.py
```

首次執行會自動開啟設定視窗，填入 API Key 即可使用。

---

### 方式 B：打包成可攜式執行檔（推薦）

**步驟 1｜先依照方式 A 安裝依賴並確認可正常執行**

**步驟 2｜打包**

```bash
python build.py
```

- Mac：產生 `dist/VoiceInput.app`，直接雙擊或拖入「應用程式」資料夾
- Windows：產生 `dist/VoiceInput.exe`，直接雙擊

打包後不需要 Python 環境，可以複製到任何電腦使用。

---

## ⚙️ 設定

第一次啟動會自動開啟設定視窗。之後可以右鍵點擊系統列圖示 → **設定 / API Key**。

| 設定項目 | 說明 |
|----------|------|
| 語音辨識引擎 | 本地（mlx-whisper，預設）或雲端（OpenAI Whisper API） |
| OpenAI API Key | 使用雲端辨識或 GPT 後處理時需要（本地辨識不需要） |
| Anthropic API Key | 選填，用於 Claude 後處理（更好的中文整理） |
| 啟用智慧後處理 | 開啟後自動移除語助詞、整理句子 |
| 後處理模型 | 選 Claude（Anthropic）或 GPT-4o mini（OpenAI） |
| 自訂字典 | 指定人名、專有名詞的正確寫法，一行一個詞 |

取得 API Key：
- OpenAI：https://platform.openai.com/api-keys
- Anthropic：https://console.anthropic.com/

---

## 📖 使用方式

1. 在你想輸入文字的地方，**先點一下文字框**（讓它取得焦點）
2. **按住**右 Command（Mac）或右 Ctrl（Windows）
3. 說話（可以中英混說）
4. **放開**快捷鍵
5. 等待處理完成（本地辨識約 1~2 秒，雲端約 2~3 秒），文字自動出現在文字框

### 系統列圖示顏色
| 顏色 | 狀態 |
|------|------|
| 🔵 藍色 | 待機中 |
| 🔴 紅色 | 錄音中 |
| 🟠 橙色 | 處理中（API 呼叫）|

---

## ⚠️ 注意事項

### macOS 權限

首次執行需要授予兩個權限（只需一次）：

1. **麥克風**：系統設定 → 隱私權與安全性 → 麥克風
2. **輔助使用（Accessibility）**：系統設定 → 隱私權與安全性 → 輔助使用

若沒有授予輔助使用權限，模擬 Cmd+V 無法作用。

### Windows

通常不需要特別設定。若某些受 UAC 保護的視窗（如系統對話框）無法貼入，屬正常限制。

---

## 💡 常見問題

**Q：說話後沒有反應？**
A：確認麥克風權限已授予。若使用雲端辨識，檢查 OpenAI API Key 是否正確。

**Q：文字沒有貼到正確位置？**  
A：放開快捷鍵前，確認目標文字框已取得焦點（有游標閃爍）。

**Q：中文亂碼或辨識錯誤？**  
A：Whisper 對普通話辨識效果很好，確認設定中 language 為 `zh`。

**Q：想關閉後處理？**  
A：在設定視窗取消勾選「啟用智慧後處理」。

**Q：macOS 說「無法打開，因為無法驗證開發者」？**  
A：在 Finder 中右鍵點擊 VoiceInput.app → 開啟，或至「系統設定 → 隱私權與安全性」允許開啟。

---

## 🔧 費用估算

以每天說話 10 分鐘為例：

| 服務 | 費率 | 每月費用（估算）|
|------|------|----------------|
| 本地 mlx-whisper（預設） | 免費 | $0 |
| Whisper API（雲端） | $0.006 / 分鐘 | ~$1.8 |
| Claude Haiku（後處理） | ~$0.001 / 次 | ~$0.3 |
| GPT-4o mini（後處理） | ~$0.001 / 次 | ~$0.3 |

> 使用本地辨識 + Claude Haiku 後處理，每月約 $0.3。

---

## 📄 授權

MIT License — 自由使用、修改、散布
