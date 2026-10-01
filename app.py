import os
import json
import pandas as pd
import streamlit as st
from datetime import datetime
import google.generativeai as genai
import requests

# --- 1. 頁面基本設定 ---
st.set_page_config(page_title="AI 智慧記帳助手", page_icon="💰", layout="centered")

# --- 2. 系統設定與連線 (Supabase REST API & Gemini) ---
SUPABASE_URL = st.secrets["SUPABASE_URL"].rstrip("/")
SUPABASE_KEY = st.secrets["SUPABASE_KEY"]

HEADERS = {
    "apikey": SUPABASE_KEY,
    "Authorization": f"Bearer {SUPABASE_KEY}",
    "Content-Type": "application/json",
    "Prefer": "return=representation"
}

# 模型名稱可在 Streamlit Secrets 加上 GEMINI_MODEL 覆蓋，未設定則用預設值
MODEL_NAME = st.secrets.get("GEMINI_MODEL", "gemini-2.5-flash")

api_key = st.secrets.get("GEMINI_API_KEY")
if api_key:
    genai.configure(api_key=api_key)
    model = genai.GenerativeModel(MODEL_NAME)
else:
    st.warning("⚠️ 尚未設定 GEMINI_API_KEY，圖片辨識功能將無法使用。")

# --- 3. 資料庫操作函數 ---
def load_user_data(user_id):
    url = f"{SUPABASE_URL}/rest/v1/transactions?user_id=eq.{user_id}&order=date.desc"
    response = requests.get(url, headers=HEADERS)
    if response.status_code == 200:
        data = response.json()
        return pd.DataFrame(data)
    return pd.DataFrame(columns=["date", "category", "store", "amount", "source"])

def add_transaction(user_id, date, category, store, amount, source):
    url = f"{SUPABASE_URL}/rest/v1/transactions"
    data = {
        "user_id": user_id,
        "date": str(date),
        "category": category,
        "store": store,
        "amount": amount,
        "source": source
    }
    response = requests.post(url, headers=HEADERS, json=data)
    if response.status_code not in (200, 201):
        raise Exception(f"寫入資料庫失敗 ({response.status_code})：{response.text}")

def to_int_amount(value):
    """把 AI 回傳的金額轉成整數，容許 '1,200'、'$59' 這類格式"""
    if isinstance(value, (int, float)):
        return int(value)
    cleaned = "".join(ch for ch in str(value) if ch.isdigit() or ch in ".-")
    return int(float(cleaned)) if cleaned else 0

# --- 4. 免密碼專屬網址登入系統 ---

# 讀取網址列的參數 (例如 ?user=tom123)
query_params = st.query_params

if "logged_in" not in st.session_state:
    st.session_state.logged_in = False
if "current_user" not in st.session_state:
    st.session_state.current_user = ""

# 如果網址有帶 user 參數，直接自動登入
if "user" in query_params:
    st.session_state.logged_in = True
    st.session_state.current_user = query_params["user"]

# 如果沒有登入狀態，顯示首頁提示
if not st.session_state.logged_in:
    st.title("🔐 AI 記帳本")
    st.info("💡 請使用您的「專屬網址」進入系統。")
    st.write("第一次使用？請在下方建立您的專屬識別碼（這將作為您的隱私鑰匙）：")
    
    new_user_id = st.text_input("輸入新的專屬識別碼 (建議使用英文+數字，例如：john_9527)")
    if st.button("建立並進入"):
        if new_user_id:
            st.session_state.logged_in = True
            st.session_state.current_user = new_user_id
            st.rerun()
        else:
            st.error("請輸入識別碼！")
    st.stop()

# --- 主畫面 ---
current_user = st.session_state.current_user

col_title, col_logout = st.columns([4, 1])
with col_title:
    st.title(f"💰 {current_user} 的 AI 記帳本")
with col_logout:
    st.write("")
    if st.button("登出"):
        st.session_state.logged_in = False
        st.session_state.current_user = ""
        st.rerun()

# --- 5. 側邊欄：新增記帳 ---
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
            try:
                add_transaction(current_user, date, category, store, amount, "手動")
                st.sidebar.success("新增成功！")
                st.rerun()
            except Exception as e:
                st.sidebar.error(str(e))

elif tab_choice == "上傳發票/截圖":
    uploaded_file = st.sidebar.file_uploader("上傳發票或網購/銀行明細截圖", type=["jpg", "jpeg", "png"])

    if uploaded_file and api_key:
        st.sidebar.image(uploaded_file, caption="上傳的圖片", width="stretch")

        if st.sidebar.button("🤖 AI 自動辨識並記帳"):
            with st.spinner("AI 正在分析圖片內容...這可能需要幾秒鐘"):
                try:
                    image_bytes = uploaded_file.getvalue()
                    image_part = {
                        "mime_type": uploaded_file.type,
                        "data": image_bytes
                    }

                    prompt = f"""這是一張銀行消費明細或發票的截圖。
請幫我把裡面「所有」的消費紀錄都抓出來。
請嚴格以 JSON 陣列 (JSON array) 的格式回傳，不要包含任何其他說明文字。

JSON 格式範例：
[
  {{
    "date": "YYYY-MM-DD",
    "store": "商店或項目名稱",
    "amount": 數字金額,
    "category": "請從 {', '.join(CATEGORIES)} 中選一個最適合的分類"
  }}
]"""

                    response = model.generate_content([image_part, prompt])
                    result_text = response.text.strip()

                    # 去除可能的 markdown 程式碼區塊標記
                    if result_text.startswith("```json"):
                        result_text = result_text[7:-3].strip()
                    elif result_text.startswith("```"):
                        result_text = result_text[3:-3].strip()

                    transactions_data = json.loads(result_text)
                    success_count = 0

                    for t in transactions_data:
                        store_name = t.get("store", "未知商店")
                        amount_val = to_int_amount(t.get("amount", 0))
                        cat_val = t.get("category", "其他")
                        if cat_val not in CATEGORIES:
                            cat_val = "其他"
                        date_str = t.get("date")

                        if not date_str:
                            date_str = str(datetime.today().date())

                        add_transaction(current_user, date_str, cat_val, store_name, amount_val, "AI截圖批次")
                        success_count += 1

                    st.sidebar.success(f"成功辨識並新增了 {success_count} 筆記帳！")
                    st.rerun()

                except json.JSONDecodeError:
                    st.sidebar.error("AI 回傳的格式不正確，請再試一次。")
                except Exception as e:
                    st.sidebar.error(f"辨識失敗：{e}")

# --- 6. 主畫面：圖表與明細 ---
st.subheader("📊 消費總覽與記錄")

df = load_user_data(current_user)

if not df.empty and "amount" in df.columns:
    total_spent = df["amount"].sum()
    st.metric(label="累積總支出", value=f"NT$ {total_spent:,}")

    col1, col2 = st.columns(2)
    with col1:
        st.write("### 類別支出佔比")
        category_group = df.groupby("category")["amount"].sum()
        st.bar_chart(category_group)

    with col2:
        st.write("### 詳細明細表")
        display_df = df[["date", "category", "store", "amount", "source"]].rename(
            columns={"date": "日期", "category": "類別", "store": "商店/項目", "amount": "金額", "source": "來源"}
        )
        st.dataframe(display_df, use_container_width=True)

    csv = display_df.to_csv(index=False).encode("utf-8")
    st.download_button(label="📥 下載個人記帳 CSV", data=csv, file_name=f"{current_user}_expenses.csv", mime="text/csv")
else:
    st.info("目前尚無記帳資料，請從左側新增手動記帳或上傳發票截圖開始體驗！")
