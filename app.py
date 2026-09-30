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

# --- 4. 簡單登入系統 ---
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
            st.rerun()
        else:
            st.error("帳號或密碼錯誤！")

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

if
