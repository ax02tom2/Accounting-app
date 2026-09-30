import os
import pandas as pd
import streamlit as st
from datetime import datetime
import google.generativeai as genai
from supabase import create_client, Client

# --- 1. 頁面基本設定 ---
st.set_page_config(page_title="AI 智慧記帳助手", page_icon="💰", layout="centered")

# --- 2. 系統設定與連線 (Supabase & Gemini) ---
# 利用 @st.cache_resource 快取資料庫連線，避免網頁一直重複連線
@st.cache_resource
def init_connection():
    url = st.secrets["SUPABASE_URL"]
    key = st.secrets["SUPABASE_KEY"]
    return create_client(url, key)

supabase = init_connection()

api_key = st.secrets.get("GEMINI_API_KEY")
if api_key:
    genai.configure(api_key=api_key)
    model = genai.GenerativeModel("gemini-2.5-flash")
else:
    st.warning("⚠️ 尚未設定 GEMINI_API_KEY，圖片辨識功能將無法使用。")

# --- 3. 資料庫操作函數 ---
def load_user_data(user_id):
    # 從資料庫抓取該使用者的記帳紀錄，按時間遞減排序
    response = supabase.table("transactions").select("*").eq("user_id", user_id).order("date", desc=True).execute()
    return pd.DataFrame(response.data)

def add_transaction(user_id, date, category, store, amount, source):
    # 將新資料寫入資料庫
    data = {
        "user_id": user_id,
        "date": str(date),
        "category": category,
        "store": store,
        "amount": amount,
        "source": source
    }
    supabase.table("transactions").insert(data).execute()

# --- 4. 簡單登入系統 ---
# ⚠️ 這裡可以自訂您和親友的帳號密碼 (格式："帳號": "密碼")
USERS = {
    "tom": "1234",
    "friend": "5678",
    "guest": "0000"
}

if "logged_in" not in st.session_state:
    st.session_state.logged_in = False
if "current_user" not in st.session_state:
    st.session_state.current_user = ""

if not st.session_state.logged_in:
    st.title("🔐 AI 記帳本 - 登入")
    st.write("請輸入帳號密碼以讀取您的專屬記帳資料。")
    username = st.text_input("帳號 (例如: tom)")
    password = st.text_input("密碼", type="password")
    
    if st.button("登入"):
        if username in USERS and USERS[username] == password:
            st.session_state.logged_in = True
            st.session_state.current_user = username
            st.rerun() # 登入成功，重新整理頁面
        else:
            st.error("帳號或密碼錯誤！")
    
    st.stop() # 停止執行下方的程式碼，直到使用者成功登入

# --- 以下為登入後的主畫面 ---
current_user = st.session_state.current_user

# 顯示標題與登出按鈕
col_title, col_logout = st.columns([4, 1])
with col_title:
    st.title(f"💰 {current_user} 的 AI 記帳本")
with col_logout:
    st.write("") # 排版用
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
            add_transaction(current_user, date, category, store, amount, "手動")
            st.sidebar.success("新增成功！")
            st.rerun() # 新增後重整頁面，讓主畫面圖表更新

elif tab_choice == "上傳發票/截圖":
    uploaded_file = st.sidebar.file_uploader("上傳發票或網購結帳截圖", type=["jpg", "jpeg", "png"])
    if uploaded_file and api_key:
        st.sidebar.image(uploaded_file, caption="上傳的圖片", use_column_width=True)
        if st.sidebar.button("🤖 AI 自動辨識並記帳"):
            with st.spinner("AI 正在分析圖片內容..."):
                try:
                    image_bytes = uploaded_file.getvalue()
                    image_part = {"mime_type": uploaded_file.type, "data": image_bytes}
                    
                    prompt = f"""請分析這張發票或購物截圖，並嚴格依照以下格式回傳：
商店: xxx
金額: 000
類別: 從 {", ".join(CATEGORIES)} 中選一個最適合的"""
                    
                    response = model.generate_content([image_part, prompt])
                    lines = response.text.strip().split("\n")
                    
                    parsed_data = {}
                    for line in lines:
                        if ":" in line:
                            k, v = line.split(":", 1)
                            parsed_data[k.strip()] = v.strip()

                    store_name = parsed_data.get("商店", "未知商店")
                    # 過濾掉雜訊，只保留數字字元
                    amount_str = "".join(filter(str.isdigit, parsed_data.get("金額", "0")))
                    amount_val = int(amount_str) if amount_str else 0
                    cat_val = parsed_data.get("類別", "其他")

                    # 寫入資料庫
                    add_transaction(current_user, datetime.today().date(), cat_val, store_name, amount_val, "AI辨識")
                    st.sidebar.success(f"成功新增：{store_name} ${amount_val}")
                    st.rerun()
                except Exception as e:
                    st.sidebar.error(f"辨識失敗：{e}")

# --- 6. 主畫面：圖表與明細 ---
st.subheader("📊 消費總覽與記錄")

# 每次渲染畫面時，從 Supabase 抓取當前使用者的最新資料
df = load_user_data(current_user)

if not df.empty:
    total_spent = df["amount"].sum()
    st.metric(label="累積總支出", value=f"NT$ {total_spent:,}")

    col1, col2 = st.columns(2)
    with col1:
        st.write("### 類別支出佔比")
        category_group = df.groupby("category")["amount"].sum()
        st.bar_chart(category_group)

    with col2:
        st.write("### 詳細明細表")
        # 整理成中文欄位名稱方便閱讀
        display_df = df[["date", "category", "store", "amount", "source"]].rename(
            columns={"date": "日期", "category": "類別", "store": "商店/項目", "amount": "金額", "source": "來源"}
        )
        st.dataframe(display_df, use_container_width=True)

    csv = display_df.to_csv(index=False).encode("utf-8")
    st.download_button(label="📥 下載個人記帳 CSV", data=csv, file_name=f"{current_user}_expenses.csv", mime="text/csv")
else:
    st.info("目前尚無記帳資料，請從左側新增手動記帳或上傳發票截圖開始體驗！")
