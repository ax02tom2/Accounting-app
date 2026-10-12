🐾 記帳助手 (AI Accounting App)

這是一套基於 Streamlit 建立，結合 Google Gemini AI 進行圖像辨識與 Supabase 雲端資料庫的跨平台個人記帳系統。

🎯 核心開發原則 (給未來 AI 助手的系統指引)

任何針對本專案的代碼修改，必須嚴格遵守以下開發原則：

單一檔案架構 (Single-File Mandate): 所有的網頁 UI 邏輯、API 呼叫與後端操作皆整合在單一 app.py 中。

AI JSON 原生輸出: 操作 Gemini generate_content 時，必須使用 generation_config={"response_mime_type": "application/json"} 確保穩定回傳 JSON 結構，嚴禁使用 ````json` 字串切割來解析。

具體的錯誤捕捉: 所有的 try...except 區塊，報錯時必須完整印出 str(e) 讓使用者了解具體原因，例如：st.error(f"寫入失敗，詳細原因：{str(e)}")。

無終端機作業環境: 部署環境為 Streamlit Cloud + GitHub。提供程式碼更新時，請直接輸出完整的 app.py 供使用者覆蓋，不需要提供終端機 pip install 指令。

資料庫穩定性: 堅持使用標準 requests 庫直接呼叫 Supabase REST API 進行 CRUD (避免官方套件相容性衝突)。

🛠️ 技術棧 (Tech Stack)

前端/框架: Python Streamlit

視覺圖表: Plotly Express (圓餅/甜甜圈圖)

資料庫: Supabase (REST API 模式)

AI 核心: Google Gemini 2.5 Flash

狀態記憶: streamlit-cookies-controller (實現免密碼持久化登入)

資料處理: Pandas

🚀 核心功能介紹

1. 跨平台免密碼登入 (Magic Link / Cookie)

拋棄傳統帳密。透過 URL 參數 (?user=xxxx) 建立專屬通道。

讀取參數後寫入手機/瀏覽器 Cookie，實現「加入主畫面即成為獨立永久登入 App」。

2. 視覺化 UI (Glassmorphism 玻璃擬物風格)

使用 CSS 建立半透明卡片與毛玻璃特效 (backdrop-filter: blur)。

支援讀取本機端 bg.jpg 並自動套用 65% 白色半透明漸層遮罩，避免背景過於搶眼。

3. 智慧截圖辨識 (AI OCR + 解析)

支援多圖批次上傳 (發票、銀行截圖、網購訂單、行動支付)。

自訂 Prompt，能自動過濾「非實際支出」(如轉帳給朋友、儲值、點數回饋)。

內建「疑似重複防呆」：比對資料庫與批次陣列，若日期相近(DUP_DAYS = 3)且金額相同，會標記警告並預設取消勾選。

4. 儀表板與互動明細表

自動依據交易日期生成「月份選擇器」。

Tab 分頁設計，解決手機版面擁擠問題。

支援使用 st.data_editor 進行互動，提供勾選刪除功能 (藉由提取 Supabase 資料表原生的 id 欄位操作)。

支援單月 CSV 資料匯出。

📦 資料表結構 (transactions)

Supabase 上的表格包含以下必備欄位：

id: 唯一識別碼 (Primary Key)

user_id: 綁定使用者的專屬識別碼字串

date: 消費日期 (YYYY-MM-DD)

category: 消費類別 (生活費用, 娛樂費用, 餐飲美食, 交通運輸, 房租帳單, 其他)

store: 商店或項目名稱

amount: 消費金額 (正整數)

source: 來源紀錄 (如手動、AI截圖-銀行明細)
