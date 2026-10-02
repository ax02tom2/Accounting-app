import json
import base64
import pandas as pd
import streamlit as st
from datetime import datetime
import google.generativeai as genai
import requests
from streamlit_cookies_controller import CookieController
import plotly.express as px

# --- 1. 頁面基本設定 ---
st.set_page_config(page_title="記帳助手", page_icon="🐾", layout="centered")


def stretch(fn, *args, **kwargs):
    """相容不同 Streamlit 版本：依序嘗試 width='stretch' / use_container_width / 不帶參數"""
    for extra in ({"width": "stretch"}, {"use_container_width": True}, {}):
        try:
            return fn(*args, **kwargs, **extra)
        except Exception:
            continue
    return fn(*args, **kwargs)


def get_base64_image(image_path):
    """讀取本機圖片並轉成 Base64 供網頁 CSS 使用"""
    try:
        with open(image_path, "rb") as img_file:
            return base64.b64encode(img_file.read()).decode()
    except Exception:
        return None


local_bg_path = "bg.jpg"
bg_base64 = get_base64_image(local_bg_path)

if bg_base64:
    bg_image_css = f"url('data:image/jpeg;base64,{bg_base64}')"
else:
    bg_image_css = "url('https://images.unsplash.com/photo-1473448912268-2022ce9509d8?q=80&w=2000&auto=format&fit=crop')"

st.markdown(f"""
<style>
.stApp {{
    background-image: linear-gradient(rgba(255, 255, 255, 0.65), rgba(255, 255, 255, 0.65)), {bg_image_css};
    background-size: cover;
    background-position: center;
    background-attachment: fixed;
    background-repeat: no-repeat;
}}
[data-testid="stHeader"] {{
    background-color: rgba(0,0,0,0);
}}
[data-testid="stSidebar"] {{
    background-color: rgba(255, 255, 255, 0.85);
    backdrop-filter: blur(10px);
    border-right: 1px solid rgba(255,255,255,0.3);
}}
[data-testid="stDataFrame"], [data-testid="stMetric"] {{
    background-color: rgba(255, 255, 255, 0.75);
    border-radius: 16px;
    padding: 15px;
    box-shadow: 0 8px 32px 0 rgba(31, 38, 135, 0.07);
    backdrop-filter: blur(8px);
    -webkit-backdrop-filter: blur(8px);
    border: 1px solid rgba(255, 255, 255, 0.5);
}}
.stTabs [data-baseweb="tab"] {{
    background-color: rgba(255, 255, 255, 0.6);
    border-radius: 10px 10px 0 0;
    margin-right: 5px;
    border: 1px solid rgba(255, 255, 255, 0.5);
}}
</style>
""", unsafe_allow_html=True)

controller = CookieController()

# --- 2. 系統設定與連線 ---
SUPABASE_URL = st.secrets["SUPABASE_URL"].rstrip("/")
SUPABASE_KEY = st.secrets["SUPABASE_KEY"]

HEADERS = {
    "apikey": SUPABASE_KEY,
    "Authorization": f"Bearer {SUPABASE_KEY}",
    "Content-Type": "application/json",
    "Prefer": "return=representation",
}

MODEL_NAME = st.secrets.get("GEMINI_MODEL", "gemini-2.5-flash")
api_key = st.secrets.get("GEMINI_API_KEY")

if api_key:
    genai.configure(api_key=api_key)
    model = genai.GenerativeModel(MODEL_NAME)
else:
    st.warning("⚠️ 尚未設定 GEMINI_API_KEY，圖片辨識功能將無法使用。")

CATEGORIES = ["生活費用", "娛樂費用", "餐飲美食", "交通運輸", "房租帳單", "其他"]
DUP_DAYS = 3  # 金額相同且日期相差 N 天內，視為疑似重複


# --- 3. 資料庫操作函數 ---
def load_user_data(user_id):
    url = f"{SUPABASE_URL}/rest/v1/transactions?user_id=eq.{user_id}&order=date.desc"
    response = requests.get(url, headers=HEADERS)
    if response.status_code == 200:
        return pd.DataFrame(response.json())
    return pd.DataFrame(columns=["date", "category", "store", "amount", "source"])


def add_transaction(user_id, date, category, store, amount, source):
    url = f"{SUPABASE_URL}/rest/v1/transactions"
    data = {
        "user_id": user_id,
        "date": str(date),
        "category": category,
        "store": store,
        "amount": amount,
        "source": source,
    }
    response = requests.post(url, headers=HEADERS, json=data)
    if response.status_code not in (200, 201):
        raise Exception(f"寫入資料庫失敗 ({response.status_code})：{response.text}")


def to_int_amount(value):
    if isinstance(value, (int, float)):
        return int(value)
    cleaned = "".join(ch for ch in str(value) if ch.isdigit() or ch in ".-")
    return int(float(cleaned)) if cleaned else 0


# --- 3.5 AI 截圖辨識 ---
def build_prompt():
    now = datetime.today()
    today = now.strftime("%Y-%m-%d")
    roc_year = now.year - 1911
    return f"""今天日期是 {today}（民國 {roc_year} 年）。這是一張「消費相關」的手機截圖或照片，可能是：
(A) 銀行／信用卡消費明細（每筆有日期、商店、金額）
(B) 購物 App 訂單頁（蝦皮、momo 等，一張訂單可能含多個商品）
(C) 行動支付紀錄：LINE Pay、街口支付、悠遊付、Apple Pay/Google Pay 通知等
(D) 發票／收據／購物明細的照片（可能歪斜、反光、折痕）

請抽出所有「實際支出」，嚴格只回傳 JSON 陣列，不要任何說明文字。規則：

【通用】
1. date：格式 YYYY-MM-DD。畫面上沒有日期就填 null；只有月/日就用今年補上年份。
   若是民國年（如 115/10/02、115年10月），請換算成西元（民國年 + 1911）。
2. store：精簡商店名稱，去掉「股份有限公司」「有限公司」等字尾。
   例：「全家便利商店股份有限公司」→「全家便利商店」；「樂購蝦皮股份有限公司」→「蝦皮購物」；「UBER FORMOSA CO.LTD」→「Uber」。
3. amount：正整數（新台幣），不含 $ 與逗號。一律使用「實際付款金額」（扣掉折扣、點數、折價券之後），不是原價。
4. category 只能從 {', '.join(CATEGORIES)} 中選一個最適合的。
5. source_type 只能是：銀行明細、訂單、行動支付、發票收據、其他。
6. 退款、取消、不成立、授權失敗的交易請略過；卡片名稱、可用額度、點數回饋、「注意事項」等不是消費，請忽略。

【訂單頁 (B)】
一張訂單只記「一筆」，金額使用「訂單金額」（不是各商品價格加總）。
store 格式：「蝦皮｜賣場名（商品簡稱等N件）」。

【行動支付 (C)】
- 只記「付款給商店／繳費」的支出，store 用商店名稱。
- 以下不是消費，請略過：儲值／加值、收到的款項／收款、轉入、點數回饋、退款。
- 個人轉帳（轉給朋友）若明確是「轉出」才記，store 寫「轉帳｜對象名」，category 用「其他」。

【發票／收據 (D)】
- 一張發票只記「一筆」，金額使用「總計／合計／應付」，不要逐項記品項。
- store 用賣方（店家）名稱；日期用發票/交易日期；若有「發票號碼」不需要輸出。
- 發票上若是多行品項，可在 store 後加註「（主要品項）」例如「全聯（生鮮雜貨）」。
- 字跡模糊到無法確定金額或店名時，請略過該筆，不要猜測。

JSON 格式：
[{{"date": "YYYY-MM-DD 或 null", "store": "名稱", "amount": 123, "category": "分類", "source_type": "銀行明細"}}]"""


def parse_json_text(text):
    text = text.strip()
    if text.startswith("```"):
        text = text.strip("`")
        if text.lower().startswith("json"):
            text = text[4:]
    data = json.loads(text.strip())
    if isinstance(data, dict):  # 偶爾會被包在物件裡
        for v in data.values():
            if isinstance(v, list):
                return v
        return [data]
    return data


def extract_from_image(uploaded_file):
    image_part = {"mime_type": uploaded_file.type, "data": uploaded_file.getvalue()}
    response = model.generate_content(
        [image_part, build_prompt()],
        generation_config={"response_mime_type": "application/json", "temperature": 0},
    )
    return parse_json_text(response.text)


def mark_duplicates(pending, existing):
    """標記疑似重複：與資料庫已有紀錄、或本批其他筆，金額相同且日期相近"""
    ex = pd.DataFrame()
    if existing is not None and not existing.empty and "amount" in existing.columns:
        ex = existing.copy()
        ex["date"] = pd.to_datetime(ex["date"])
    tol = pd.Timedelta(days=DUP_DAYS)
    notes, seen = [], []
    for _, r in pending.iterrows():
        d = pd.Timestamp(r["date"])
        note = ""
        if not ex.empty:
            m = ex[(ex["amount"] == r["amount"]) & ((ex["date"] - d).abs() <= tol)]
            if not m.empty:
                note = "⚠️ 疑似與已記錄重複"
        if not note:
            for sd, sa in seen:
                if sa == r["amount"] and abs(sd - d) <= tol:
                    note = "⚠️ 疑似與本批其他筆重複"
                    break
        seen.append((d, r["amount"]))
        notes.append(note)
    return notes


# --- 4. 免密碼 Cookie 登入 ---
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
    st.title("🐾 記帳助手")
    st.caption(f"👤 使用者：{current_user}")
with col_logout:
    st.write("")
    if stretch(st.button, "登出"):
        controller.remove("saved_user")
        st.query_params.clear()
        st.session_state.logged_in = False
        st.session_state.current_user = ""
        st.rerun()

# --- 5. 側邊欄：新增記帳 ---
st.sidebar.header("➕ 新增記帳")
tab_choice = st.sidebar.radio("選擇輸入方式", ["手動輸入", "上傳發票/截圖"])

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
    st.sidebar.caption("支援：銀行/信用卡明細、蝦皮等訂單頁、LINE Pay/街口等行動支付、發票收據照片。可一次選多張。")
    uploaded_files = st.sidebar.file_uploader(
        "上傳消費截圖", type=["jpg", "jpeg", "png", "webp"], accept_multiple_files=True
    )
    if uploaded_files and api_key:
        for f in uploaded_files:
            stretch(st.sidebar.image, f, caption=f.name)

        if st.sidebar.button("🤖 AI 辨識（先預覽再記帳）"):
            rows, errors = [], []
            progress = st.sidebar.progress(0.0, text="辨識中…")
            for i, f in enumerate(uploaded_files):
                try:
                    for t in extract_from_image(f):
                        amt = to_int_amount(t.get("amount", 0))
                        if amt <= 0:
                            continue
                        cat = t.get("category", "其他")
                        if cat not in CATEGORIES:
                            cat = "其他"
                        d = pd.to_datetime(t.get("date"), errors="coerce")
                        if pd.isna(d):
                            d = pd.Timestamp(datetime.today().date())  # 沒日期先用今天，可在預覽表修改
                        rows.append({
                            "匯入": True,
                            "date": d.date(),
                            "category": cat,
                            "store": str(t.get("store") or "未知商店"),
                            "amount": amt,
                            "source": "AI截圖-" + str(t.get("source_type") or "其他"),
                        })
                except Exception as e:
                    errors.append(f"{f.name}：{e}")
                progress.progress((i + 1) / len(uploaded_files), text=f"已處理 {i + 1}/{len(uploaded_files)}")
            progress.empty()

            if rows:
                pending = pd.DataFrame(rows)
                pending["提醒"] = mark_duplicates(pending, load_user_data(current_user))
                pending["匯入"] = pending["提醒"] == ""  # 疑似重複預設不勾選
                st.session_state["pending_df"] = pending
                st.session_state.pop("pending_editor", None)
            for msg in errors:
                st.sidebar.error(f"辨識失敗 → {msg}")
            if rows:
                st.rerun()

# --- 5.5 辨識結果確認區 ---
if "pending_df" in st.session_state:
    st.subheader("🔍 請確認辨識結果")
    st.caption("可直接修改日期、類別、店名、金額；取消勾選的不會寫入。"
               "有 ⚠️ 的是疑似重複（例如蝦皮訂單與信用卡帳單是同一筆），預設不勾選。")
    edited = st.data_editor(
        st.session_state["pending_df"],
        column_config={
            "匯入": st.column_config.CheckboxColumn("匯入"),
            "date": st.column_config.DateColumn("日期", format="YYYY-MM-DD"),
            "category": st.column_config.SelectboxColumn("類別", options=CATEGORIES),
            "store": st.column_config.TextColumn("商店/項目"),
            "amount": st.column_config.NumberColumn("金額", min_value=0, step=1),
            "source": st.column_config.TextColumn("來源", disabled=True),
            "提醒": st.column_config.TextColumn("提醒", disabled=True),
        },
        hide_index=True,
        key="pending_editor",
    )
    c1, c2 = st.columns(2)
    with c1:
        if stretch(st.button, "✅ 確認寫入", type="primary"):
            n = 0
            try:
                for _, r in edited[edited["匯入"] == True].iterrows():  # noqa: E712
                    d = pd.to_datetime(r["date"]).strftime("%Y-%m-%d")
                    add_transaction(current_user, d, r["category"], r["store"],
                                    to_int_amount(r["amount"]), r.get("source") or "AI截圖")
                    n += 1
                st.session_state.pop("pending_df", None)
                st.session_state.pop("pending_editor", None)
                st.success(f"已新增 {n} 筆記帳！")
                st.rerun()
            except Exception as e:
                st.error(str(e))
    with c2:
        if stretch(st.button, "🗑️ 全部捨棄"):
            st.session_state.pop("pending_df", None)
            st.session_state.pop("pending_editor", None)
            st.rerun()

# --- 6. 主畫面：圖表與明細 ---
st.divider()

df = load_user_data(current_user)

if not df.empty and "amount" in df.columns:
    df["date"] = pd.to_datetime(df["date"])
    df["month"] = df["date"].dt.strftime("%Y-%m")

    all_months = sorted(df["month"].unique(), reverse=True)

    col_filter, col_metric = st.columns([1, 1])
    with col_filter:
        selected_month = st.selectbox("📅 選擇月份", ["全部紀錄"] + all_months)

    if selected_month == "全部紀錄":
        filtered_df = df
        display_title = "累積總支出"
    else:
        filtered_df = df[df["month"] == selected_month]
        display_title = f"{selected_month} 月總支出"

    total_spent = filtered_df["amount"].sum()

    with col_metric:
        st.metric(label=display_title, value=f"NT$ {total_spent:,}")

    if not filtered_df.empty:
        tab_chart, tab_table = st.tabs(["📊 類別圓餅圖", "📝 該月詳細明細"])

        with tab_chart:
            category_group = filtered_df.groupby("category", as_index=False)["amount"].sum()
            fig = px.pie(
                category_group,
                values="amount",
                names="category",
                hole=0.4,
                color_discrete_sequence=px.colors.qualitative.Pastel,
            )
            fig.update_traces(
                textposition="inside",
                textinfo="label+percent",
                hovertemplate="<b>%{label}</b><br>金額: NT$ %{value:,}<br>佔比: %{percent}<extra></extra>",
            )
            fig.update_layout(
                showlegend=False,
                margin=dict(t=10, b=10, l=10, r=10),
                paper_bgcolor="rgba(0,0,0,0)",
                plot_bgcolor="rgba(0,0,0,0)",
            )
            stretch(st.plotly_chart, fig)

        with tab_table:
            display_df = filtered_df[["date", "category", "store", "amount", "source"]].copy()
            display_df["date"] = display_df["date"].dt.strftime("%Y-%m-%d")
            display_df = display_df.rename(
                columns={"date": "日期", "category": "類別", "store": "商店/項目", "amount": "金額", "source": "來源"}
            )
            stretch(st.dataframe, display_df, hide_index=True)

            csv = display_df.to_csv(index=False).encode("utf-8")
            st.download_button(
                label=f"📥 下載 {selected_month} 記帳 CSV",
                data=csv,
                file_name=f"{current_user}_expenses_{selected_month}.csv",
                mime="text/csv",
            )
    else:
        st.info(f"這個月份 ({selected_month}) 目前沒有記帳紀錄喔！")

else:
    st.info("目前尚無記帳資料，請從左側新增手動記帳或上傳發票截圖開始體驗！")
