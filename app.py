import os
from datetime import datetime
import google.generativeai as genai
import pandas as pd
import streamlit as st

# 1. 頁面基本設定
st.set_page_config(
    page_title="AI 智慧記帳本", page_icon="💰", layout="centered"
)

st.title("💰 AI 智慧記帳助手 (Streamlit)")
st.write(
    "支援手動輸入、發票與購物截圖 AI 自動辨識分類，並可串接自動化推播。"
)

# 2. 設定 Gemini API (用於圖片辨識與自動分類)
# 建議將 API Key 放在 Streamlit Secrets 或本機環境變數
api_key = st.secrets.get("GEMINI_API_KEY") or os.environ.get(
    "GEMINI_API_KEY"
)

if api_key:
  genai.configure(api_key=api_key)
  # 使用支援多模態與結構化輸出的模型
  model = genai.GenerativeModel("gemini-2.5-flash")
else:
  st.warning("⚠️ 尚未設定 GEMINI_API_KEY，圖片辨識功能將無法使用。")

# 3. 模擬資料庫 (實際部署可改用 SQLite 或 Supabase)
if "transactions" not in st.session_state:
  st.session_state.transactions = pd.DataFrame(
      columns=["日期", "類別", "項目/商店", "金額 (NT$)", "來源"]
  )

# --- 側邊欄：新增記帳選項 ---
st.sidebar.header("➕ 新增記帳")
tab_choice = st.sidebar.radio("選擇輸入方式", ["手動輸入", "上傳發票/截圖"])

CATEGORIES = ["生活費用", "娛樂費用", "餐飲美食", "交通運輸", "房租帳單", "其他"]

if tab_choice == "手動輸入":
  with st.sidebar.form("manual_form"):
    date = st.date_input("消費日期", datetime.today())
    category = st.selectbox("消費類別", CATEGORIES)
    store = st.text_input("商店或項目名稱", "例如：全聯")
    amount = st.number_input("金額", min_value=0, value=100)
    submitted = st.form_submit_button("確認新增")

    if submitted:
      new_row = pd.DataFrame({
          "日期": [str(date)],
          "類別": [category],
          "項目/商店": [store],
          "金額 (NT$)": [amount],
          "來源": ["手動"],
      })
      st.session_state.transactions = pd.concat(
          [st.session_state.transactions, new_row], ignore_index=True
      )
      st.sidebar.success("新增成功！")

elif tab_choice == "上傳發票/截圖":
  uploaded_file = st.sidebar.file_uploader(
      "上傳發票或網購結帳截圖", type=["jpg", "jpeg", "png"]
  )
  if uploaded_file and api_key:
    st.sidebar.image(
        uploaded_file, caption="上傳的圖片", use_column_width=True
    )
    if st.sidebar.button("🤖 AI 自動辨識並記帳"):
      with st.spinner("AI 正在分析圖片內容..."):
        try:
          # 將上傳的圖片轉給 Gemini 解析
          image_bytes = uploaded_file.getvalue()
          image_part = {
              "mime_type": uploaded_file.type,
              "data": image_bytes,
          }

          prompt = f"""
                    請分析這張發票或購物截圖，並提取以下資訊回傳成格式化的文字：
                    1. 項目或商店名稱 (Store)
                    2. 總金額 (Amount，只要數字)
                    3. 從下列類別中選擇最適合的一個：{", ".join(CATEGORIES)} (Category)
                    
                    請嚴格依照以下格式回傳：
                    商店: xxx
                    金額: 000
                    類別: xxx
                    """

          response = model.generate_content([image_part, prompt])
          result_text = response.text

          # 簡單解析 AI 回傳的字串
          lines = result_text.strip().split("\n")
          parsed_data = {}
          for line in lines:
            if ":" in line:
              k, v = line.split(":", 1)
              parsed_data[k.strip()] = v.strip()

          store_name = parsed_data.get("商店", "未知商店")
          amount_val = int(
              "".filter(str.isdigit, parsed_data.get("金額", "0"))
              or 0
          )
          cat_val = parsed_data.get("類別", "其他")

          # 寫入狀態
          new_row = pd.DataFrame({
              "日期": [str(datetime.today().date())],
              "類別": [cat_val if cat_val in CATEGORIES else "其他"],
              "項目/商店": [store_name],
              "金額 (NT$)": [amount_val],
              "來源": ["AI 截圖辨識"],
          })
          st.session_state.transactions = pd.concat(
              [st.session_state.transactions, new_row], ignore_index=True
          )
          st.sidebar.success(
              f"辨識成功！已新增：{store_name} ${amount_val} ({cat_val})"
          )
        except Exception as e:
          st.sidebar.error(f"辨識失敗：{e}")

# --- 主畫面：記帳資料與圖表分析 ---
st.subheader("📊 消費總覽與記錄")

df = st.session_state.transactions

if not df.empty:
  # 顯示總金額
  total_spent = df["金額 (NT$)"].sum()
  st.metric(label="本月總支出", value=f"NT$ {total_spent:,}")

  # 顯示圓餅圖分析（依類別）
  col1, col2 = st.columns(2)
  with col1:
    st.write("### 類別支出佔比")
    category_group = df.groupby("類別")["金額 (NT$)"].sum()
    st.bar_chart(category_group)

  with col2:
    st.write("### 詳細明細表")
    st.dataframe(df, use_container_width=True)

  # 匯出 CSV 按鈕
  csv = df.to_csv(index=False).encode("utf-8")
  st.download_button(
      label="📥 下載完整記帳 CSV",
      data=csv,
      file_name="expenses.csv",
      mime="text/csv",
  )
else:
  st.info(
      "目前尚無記帳資料，請從左側欄位新增手動記帳或上傳發票截圖開始體驗！"
  )