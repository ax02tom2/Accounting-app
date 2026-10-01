import os
import json
import pandas as pd
import streamlit as st
from datetime import datetime
import google.generativeai as genai
import requests
from streamlit_cookies_controller import CookieController
import plotly.express as px

# --- 1. 頁面基本設定 ---
st.set_page_config(page_title="AI 智慧記帳助手", page_icon="💰", layout="centered")

# --- ✨ 新增：美化底圖，改為現代感柔和漸層 (其他程式碼完全不變) ---
st.markdown("""
<style>
/* 主畫面背景：淺藍灰柔和漸層，視覺更舒服 */
.stApp {
    background: linear-gradient(135deg, #f5f7fa 0%, #e0e5ec 100%);
}
/* 讓頂部預設的一條白邊變透明，使漸層更完整 */
[data-testid="stHeader"] {
    background-color: rgba(0,0,0,0);
}
/* 側邊欄背景微調為極淺灰，增加立體與層次感 */
[data-testid="stSidebar"] {
    background-color: #f8f9fa;
}
/* 讓明細表格的背景保持純白，確保文字清晰易讀 */
[data-testid="stDataFrame"] {
    background-color: #ffffff;
    border-radius: 8px;
}
</style>
""", unsafe_allow_html=True)

# 初始化 Cookie 控制器
controller = CookieController()

# --- 2. 系統設定與連線 (Supabase REST API & Gemini) ---
SUPABASE_URL = st.secrets["SUPABASE_URL"].rstrip("/")
SUPABASE_KEY = st.secrets["SUPABASE_KEY"]

HEADERS = {
    "apikey": SUPABASE_KEY,
    "Authorization": f"Bearer {SUPABASE_KEY}",
    "Content-Type": "application/json",
    "Prefer": "return=representation"
}

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
    if isinstance(value, (int, float)):
        return int(value)
    cleaned = "".join(ch for ch in str(value) if ch.isdigit() or ch in ".-")
    return int(float(cleaned)) if cleaned else 0

# --- 4. 永久記憶：免密碼 Cookie 登入系統 ---
if "logged_in" not in st.session_state:
    st.session_state.logged_in = False
if "current_user" not in st.session_state:
    st.session_state.current_user = ""

saved_user = controller.get("saved_user")
query_params = st.query_params

if "user" in query_params:
    current = query_params["user"]
    st.session_state.logged_in = True
    st.session_state.current_user = current
    if saved_user != current:
        controller.set("saved_user", current)
elif saved_user:
    st.session_state.logged_in = True
    st.session_state.current_user = saved_user

if not st.session_state.logged_in:
    st.title("🔐 AI 記帳本")
    st.info("💡 第一次使用？請輸入您的專屬識別碼。登入後，您的手機將永久記住這個帳本！")
    new_user_id = st.text_input("輸入專屬識別碼 (例如：crazydog_7414)")
    if st.button("建立並進入"):
        if new_user_id:
            controller.set("saved_user", new_user_id)
            st.query_params["user"] = new_user_id 
            st.session_state.logged_in = True
            st.session_state.current_user = new_user_id
            st.rerun()
        else:
            st.error("請輸入識別碼！")
    st.stop()

# --- 主畫面頂部 ---
current_user = st.session_state.current_user

col_title, col_logout = st.columns([4, 1])
with col_title:
    st.title(f"💰 AI 記帳本")
    st.caption(f"👤 使用者：{current_user}")
with col_logout:
    st.write("")
    if st.button("登出", use_container_width=True):
        controller.remove("saved_user")
        st.query_params.clear()
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
        st.sidebar.image(uploaded_file, caption="上傳的圖片", use_column_width=True)
        if st.sidebar.button("🤖 AI 自動辨識並記帳"):
            with st.spinner("AI 正在分析圖片內容...這可能需要幾秒鐘"):
                try:
                    image_bytes = uploaded_file.getvalue()
                    image_part = {"mime_type": uploaded_file.type, "data": image_bytes}
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

                except Exception as e:
                    st.sidebar.error(f"辨識失敗，請檢查圖片或再試一次。")

# --- 6. 主畫面：圖表與明細 (大改版) ---
st.divider() # 加入分隔線讓畫面更清爽

df = load_user_data(current_user)

if not df.empty and "amount" in df.columns:
    # 處理日期與月份資料
    df["date"] = pd.to_datetime(df["date"])
    df["month"] = df["date"].dt.strftime("%Y-%m")
    
    # 取得所有月份清單 (由新到舊)
    all_months = sorted(df["month"].unique(), reverse=True)
    
    # 建立月份篩選器
    col_filter, col_metric = st.columns([1, 1])
    with col_filter:
        selected_month = st.selectbox("📅 選擇月份", ["全部紀錄"] + all_months)
    
    # 依照選擇過濾資料
    if selected_month == "全部紀錄":
        filtered_df = df
        display_title = "累積總支出"
    else:
        filtered_df = df[df["month"] == selected_month]
        display_title = f"{selected_month} 月總支出"
        
    total_spent = filtered_df["amount"].sum()
    
    with col_metric:
        # 用精美的樣式顯示總支出
        st.metric(label=display_title, value=f"NT$ {total_spent:,}")

    # 若該月有資料才顯示圖表
    if not filtered_df.empty:
        # 改用 Tabs 分頁，解決手機版面擁擠問題
        tab_chart, tab_table = st.tabs(["📊 類別圓餅圖", "📝 該月詳細明細"])
        
        with tab_chart:
            # 群組資料並繪製 Plotly 圓餅圖
            category_group = filtered_df.groupby("category", as_index=False)["amount"].sum()
            
            fig = px.pie(
                category_group, 
                values="amount", 
                names="category", 
                hole=0.4, # 變成甜甜圈圖，較現代感
                color_discrete_sequence=px.colors.qualitative.Pastel # 使用柔和繽紛的色彩
            )
            
            # 設定圓餅圖直接顯示「類別、金額、趴數」
            fig.update_traces(
                textposition='inside', 
                textinfo='label+percent',
                hovertemplate='<b>%{label}</b><br>金額: NT$ %{value:,}<br>佔比: %{percent}<extra></extra>'
            )
            
            fig.update_layout(
                showlegend=False, 
                margin=dict(t=10, b=10, l=10, r=10),
                paper_bgcolor='rgba(0,0,0,0)', # 圖表背景透明，融入我們美化的底圖
                plot_bgcolor='rgba(0,0,0,0)'
            )
            st.plotly_chart(fig, use_container_width=True)

        with tab_table:
            # 格式化表格
            display_df = filtered_df[["date", "category", "store", "amount", "source"]].copy()
            display_df["date"] = display_df["date"].dt.strftime("%Y-%m-%d")
            display_df = display_df.rename(
                columns={"date": "日期", "category": "類別", "store": "商店/項目", "amount": "金額", "source": "來源"}
            )
            
            st.dataframe(display_df, use_container_width=True, hide_index=True)
            
            # 下載該月資料按鈕
            csv = display_df.to_csv(index=False).encode("utf-8")
            st.download_button(
                label=f"📥 下載 {selected_month} 記帳 CSV", 
                data=csv, 
                file_name=f"{current_user}_expenses_{selected_month}.csv", 
                mime="text/csv"
            )
    else:
        st.info(f"這個月份 ({selected_month}) 目前沒有記帳紀錄喔！")

else:
    st.info("目前尚無記帳資料，請從左側新增手動記帳或上傳發票截圖開始體驗！")
