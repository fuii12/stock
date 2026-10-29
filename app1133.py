import csv
import hashlib
import hmac
import io
import os
import re
import sqlite3
import time
from datetime import datetime, date
import requests
import streamlit as st
from camera_input_live import camera_input_live
from PIL import Image, ImageOps, ImageDraw
from pyzbar.pyzbar import decode

LOCATIONS = ["パントリー", "冷蔵庫", "洗面所", "その他"]
OFF_URL = "https://world.openfoodfacts.org/api/v2/product/{code}.json"
DEFAULT_ICON_PATH = r"Z:\卒業研究\グループフォルダ\うちのストック\うちのストック(仮).jpg"

#
# データベース初期化
#
conn = sqlite3.connect("inventory.db", check_same_thread=False)
cursor = conn.cursor()

# ユーザーテーブル
cursor.execute("""
CREATE TABLE IF NOT EXISTS users (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    username TEXT NOT NULL UNIQUE COLLATE NOCASE,
    salt TEXT NOT NULL,
    pw_hash TEXT NOT NULL,
    line_token TEXT,
    avatar_blob BLOB,
    room_password TEXT,
    created_at TEXT
)
""")

# 在庫テーブル
cursor.execute("""
CREATE TABLE IF NOT EXISTS items (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id INTEGER NOT NULL,
    name TEXT NOT NULL,
    quantity INTEGER NOT NULL,
    location TEXT,
    jan_code TEXT,
    expiration_date TEXT,
    FOREIGN KEY (user_id) REFERENCES users(id)
)
""")

# チャットメッセージテーブル
cursor.execute("""
CREATE TABLE IF NOT EXISTS messages (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    sender_id INTEGER NOT NULL,
    receiver_id INTEGER NOT NULL,
    message TEXT,
    image_blob BLOB,
    created_at TEXT,
    FOREIGN KEY (sender_id) REFERENCES users(id),
    FOREIGN KEY (receiver_id) REFERENCES users(id)
)
""")

# カラム自動追加チェック
cursor.execute("PRAGMA table_info(items)")
cols = [r[1] for r in cursor.fetchall()]
if "jan_code" not in cols: cursor.execute("ALTER TABLE items ADD COLUMN jan_code TEXT")
if "user_id" not in cols: cursor.execute("ALTER TABLE items ADD COLUMN user_id INTEGER DEFAULT 1")
if "expiration_date" not in cols: cursor.execute("ALTER TABLE items ADD COLUMN expiration_date TEXT")

cursor.execute("PRAGMA table_info(users)")
u_cols = [r[1] for r in cursor.fetchall()]
if "line_token" not in u_cols: cursor.execute("ALTER TABLE users ADD COLUMN line_token TEXT")
if "avatar_blob" not in u_cols: cursor.execute("ALTER TABLE users ADD COLUMN avatar_blob BLOB")
if "room_password" not in u_cols: cursor.execute("ALTER TABLE users ADD COLUMN room_password TEXT")

cursor.execute("PRAGMA table_info(messages)")
m_cols = [r[1] for r in cursor.fetchall()]
if "image_blob" not in m_cols: cursor.execute("ALTER TABLE messages ADD COLUMN image_blob BLOB")

cursor.execute("CREATE UNIQUE INDEX IF NOT EXISTS idx_items_user_jan ON items(user_id, jan_code) WHERE jan_code IS NOT NULL")
conn.commit()

page_icon_img = "📦"
if os.path.exists(DEFAULT_ICON_PATH):
    try: page_icon_img = Image.open(DEFAULT_ICON_PATH)
    except Exception: pass

st.set_page_config(page_title="うちのストック Pro", page_icon=page_icon_img, layout="centered")

MODERN_CSS = """
<style>
.block-container { max-width: 760px; padding-top: 1.5rem; padding-bottom: 3rem; }
@keyframes numberPulse {
    0% { transform: scale(1); }
    50% { transform: scale(1.08); color: #ff4b4b; }
    100% { transform: scale(1); }
}
.metric-animated { animation: numberPulse 0.4s ease-in-out; }
.stButton>button, .stDownloadButton>button, [data-testid="stFormSubmitButton"]>button {
    width: 100%; min-height: 46px; border-radius: 14px; font-weight: 700;
    transition: all 0.2s cubic-bezier(0.4, 0, 0.2, 1);
    box-shadow: 0 2px 6px rgba(0,0,0,0.04);
}
.stButton>button:hover { transform: translateY(-2px); box-shadow: 0 6px 16px rgba(0,0,0,0.1); }
div[data-testid="stVerticalBlock"] > div[style*="border"] {
    border-radius: 16px !important;
    border: 1px solid rgba(150, 150, 150, 0.15) !important;
    padding: 1.2rem !important;
    background-color: rgba(255, 255, 255, 0.03);
    box-shadow: 0 4px 12px rgba(0,0,0,0.03);
}
div[class*="st-key-row_"] [data-testid="stHorizontalBlock"] {
    flex-wrap: nowrap!important; gap: .5rem; align-items: center;
}
div[class*="st-key-row_"] [data-testid="stColumn"] { min-width: 0!important; }
div[class*="st-key-row_"] [data-testid="stColumn"]:first-child { flex: 1 1 0!important; width: auto!important; }
div[class*="st-key-row_"] [data-testid="stColumn"]:not(:first-child) { flex: 0 0 54px!important; width: 54px!important; }
div[class*="st-key-row_"] .stButton>button { min-height: 42px; padding: 0; font-size: 20px; }
</style>
"""
st.markdown(MODERN_CSS, unsafe_allow_html=True)

def get_secret(name: str) -> str:
    val = os.environ.get(name, "")
    if not val:
        try: val = st.secrets.get(name, "")
        except Exception: return ""
    return val

def hash_pw(password: str, salt: bytes) -> str:
    return hashlib.pbkdf2_hmac("sha256", password.encode(), salt, 200_000).hex()

def create_user(username: str, password: str) -> bool:
    salt = os.urandom(16)
    default_blob = None
    if os.path.exists(DEFAULT_ICON_PATH):
        try:
            with open(DEFAULT_ICON_PATH, "rb") as f: default_blob = f.read()
        except Exception: pass
    try:
        cursor.execute(
            "INSERT INTO users (username, salt, pw_hash, avatar_blob, created_at) VALUES (?, ?, ?, ?, ?)",
            (username, salt.hex(), hash_pw(password, salt), default_blob, datetime.now().strftime("%Y-%m-%d %H:%M"))
        )
        conn.commit()
        return True
    except sqlite3.IntegrityError:
        conn.rollback()
        return False

def check_login(username: str, password: str):
    cursor.execute("SELECT id, salt, pw_hash, line_token, avatar_blob FROM users WHERE username = ?", (username,))
    row = cursor.fetchone()
    salt = bytes.fromhex(row[1]) if row else b"\0" * 16
    calc = hash_pw(password, salt)
    if row and hmac.compare_digest(calc, row[2]):
        return {"id": row[0], "username": username, "line_token": row[3], "avatar_blob": row[4]}
    return None

def valid_username(name: str) -> bool:
    return 2 <= len(name) <= 20 and not re.search(r"\s", name)

def send_line_notify(token: str, message: str):
    if not token: return
    try:
        requests.post("https://notify-api.line.me/api/notify", headers={"Authorization": f"Bearer {token}"}, data={"message": message}, timeout=5)
    except Exception: pass

#
# ログイン・セッション維持の管理 (タイムアウト機能付き)
#
INACTIVITY_TIMEOUT = 1800 # 30分無操作でログアウト

def require_login():
    # 無操作タイムアウトチェック
    if st.session_state.get("authed"):
        last_active = st.session_state.get("last_active", time.time())
        if time.time() - last_active > INACTIVITY_TIMEOUT:
            st.session_state.clear()
            st.warning("⚠️ 一定期間操作がなかったため、セキュリティ上ログアウトしました。")
        else:
            st.session_state["last_active"] = time.time()
            return

    st.title("📦 うちのストック")
    cursor.execute("SELECT COUNT(*) FROM users")
    n_users = cursor.fetchone()[0]
    if n_users == 0:
        st.info("まだ登録している人がいません。最初の1人目は「新規登録」から作成してください。")
    signup_open = n_users == 0 or get_secret("SIGNUP_CLOSED").lower() not in ("1", "true", "yes")

    tab_login, tab_signup = st.tabs(["ログイン", "新規登録"])
    with tab_login:
        with st.form("login_form"):
            lu = st.text_input("ユーザー名")
            lp = st.text_input("パスワード", type="password")
            if st.form_submit_button("ログイン", type="primary"):
                user_info = check_login(lu.strip(), lp)
                if user_info:
                    st.session_state["authed"] = True
                    st.session_state["user_id"] = user_info["id"]
                    st.session_state["user"] = user_info["username"]
                    st.session_state["line_token"] = user_info["line_token"]
                    st.session_state["avatar_blob"] = user_info["avatar_blob"]
                    st.session_state["viewing_uid"] = user_info["id"]
                    st.session_state["last_active"] = time.time()
                    st.rerun()
                else:
                    time.sleep(1)
                    st.error("ユーザー名またはパスワードが違います。")

    with tab_signup:
        if not signup_open:
            st.warning("現在、新規登録は締め切っています。")
        else:
            with st.form("signup_form"):
                su = st.text_input("ユーザー名 (2~20文字・空白なし)")
                sp = st.text_input("パスワード (8文字以上)", type="password")
                sp2 = st.text_input("パスワード(確認)", type="password")
                if st.form_submit_button("登録する", type="primary"):
                    su = su.strip()
                    if not valid_username(su): st.error("ユーザー名は2~20文字で空白不可です。")
                    elif len(sp) < 8: st.error("パスワードは8文字以上にしてください。")
                    elif sp != sp2: st.error("確認用パスワードが一致しません。")
                    elif not create_user(su, sp): st.error("そのユーザー名は使われています。")
                    else:
                        user_info = check_login(su, sp)
                        st.session_state["authed"] = True
                        st.session_state["user_id"] = user_info["id"]
                        st.session_state["user"] = su
                        st.session_state["line_token"] = user_info["line_token"]
                        st.session_state["avatar_blob"] = user_info["avatar_blob"]
                        st.session_state["viewing_uid"] = user_info["id"]
                        st.session_state["last_active"] = time.time()
                        st.session_state["flash"] = f"🎉 ようこそ、{su}さん！登録しました"
                        st.rerun()
                        
    st.stop()

require_login()

if "flash" in st.session_state:
    st.toast(st.session_state.pop("flash"))

def flash(msg: str):
    st.session_state["flash"] = msg

def my_uid() -> int:
    return st.session_state["user_id"]

def viewing_uid() -> int:
    return st.session_state.get("viewing_uid", st.session_state["user_id"])

def is_my_page() -> bool:
    return my_uid() == viewing_uid()

def adjust(item_id: int, delta: int):
    if not is_my_page(): return
    uid = my_uid()
    cursor.execute("SELECT name, quantity FROM items WHERE id = ? AND user_id = ?", (item_id, uid))
    row = cursor.fetchone()
    if not row: return
    
    old_qty = row[1]
    new_qty = max(0, old_qty + delta)
    cursor.execute("UPDATE items SET quantity = ? WHERE id = ? AND user_id = ?", (new_qty, item_id, uid))
    conn.commit()

    if new_qty == 0 and old_qty > 0 and st.session_state.get("line_token"):
        send_line_notify(st.session_state["line_token"], f"\n⚠️【在庫切れ通知】\n「{row[0]}」の在庫がなくなりました！買出しリストを確認してください。")

def add_item(name: str, qty: int, loc: str, jan: str, exp_date: str = None) -> bool:
    if not is_my_page(): return False
    uid = my_uid()
    try:
        cursor.execute(
            "INSERT INTO items (user_id, name, quantity, location, jan_code, expiration_date) VALUES (?, ?, ?, ?, ?, ?)",
            (uid, name, qty, loc, jan or None, exp_date or None)
        )
        conn.commit()
        st.session_state["trigger_balloons"] = True
        return True
    except sqlite3.IntegrityError:
        conn.rollback()
        return False

def decode_first(img: Image.Image):
    for obj in decode(img):
        return obj.data.decode("utf-8", errors="ignore")
    return None

def is_product_code(code: str) -> bool:
    return bool(re.fullmatch(r"\d{8}|\d{12}|\d{13}|\d{14}", code or ""))

@st.cache_data(ttl=3600, show_spinner=False)
def fetch_product_name(code: str):
    try:
        r = requests.get(
            OFF_URL.format(code=code),
            params={"fields": "product_name,product_name_ja"},
            headers={"User-Agent": "UchiNoStock/2.0"},
            timeout=15
        )
        r.raise_for_status()
        data = r.json()
        if data.get("status") != 1: return None
        p = data.get("product") or {}
        return (p.get("product_name_ja") or p.get("product_name") or "").strip() or None
    except Exception:
        return None

st.session_state.setdefault("app_title", "うちのストック")
st.session_state.setdefault("app_emoji", "📦")
st.session_state.setdefault("low_threshold", 1)

#
# サイドバー
#
with st.sidebar:
    st.header("👤 アカウント")
    avatar_data = st.session_state.get("avatar_blob")
    if avatar_data:
        try:
            img = Image.open(io.BytesIO(avatar_data))
            img = ImageOps.fit(img, (120, 120), centering=(0.5, 0.5))
            mask = Image.new("L", (120, 120), 0)
            draw = ImageDraw.Draw(mask)
            draw.ellipse((0, 0, 120, 120), fill=255)
            img.putalpha(mask)
            st.image(img, width=80)
        except Exception: pass
    
    st.caption(f"ログイン中: **{st.session_state.get('user', '')}**")
    
    if not is_my_page():
        cursor.execute("SELECT username FROM users WHERE id = ?", (viewing_uid(),))
        v_user = cursor.fetchone()
        v_name = v_user[0] if v_user else "不明"
        st.warning(f"👀 ゲスト閲覧中: **{v_name}**さんの部屋\n(変更はできません)")
        if st.button("自分の部屋に戻る"):
            st.session_state["viewing_uid"] = my_uid()
            st.rerun()

    if st.button("ログアウト"):
        st.session_state.clear()
        st.rerun()

def status_of(qty: int):
    thresh = st.session_state["low_threshold"]
    if qty == 0: return "🔴", "なし"
    if qty <= thresh: return "🟡", "あと少し"
    return "🟢", "たっぷり"

if st.session_state.get("trigger_balloons"):
    st.balloons()
    st.session_state["trigger_balloons"] = False

cursor.execute("SELECT username FROM users WHERE id = ?", (viewing_uid(),))
v_row = cursor.fetchone()
target_username = v_row[0] if v_row else st.session_state.get('user', '')

title_prefix = f"{target_username}の" if not is_my_page() else ""
st.title(f"{st.session_state['app_emoji']} {title_prefix}{st.session_state['app_title']}")
st.caption("バーコードでスマートに家庭内在庫・買い出し管理")

# 共有スペース（現在この部屋にいる人 / 覗いている人を表示）
st.info(f"👥 **ルーム共有スペース**: 現在 **{target_username}** の部屋にいます [ホスト: {target_username}]")

for _k, _v in {"current_code": None, "cam_key": 0, "up_key": 0}.items():
    st.session_state.setdefault(_k, _v)

cursor.execute("SELECT id, name, quantity, location, jan_code, expiration_date FROM items WHERE user_id = ? ORDER BY id", (viewing_uid(),))
rows = cursor.fetchall()

total_count = len(rows)
alert_count = sum(1 for r in rows if r[2] <= st.session_state["low_threshold"])

if "prev_total" not in st.session_state: st.session_state["prev_total"] = total_count
if "prev_alert" not in st.session_state: st.session_state["prev_alert"] = alert_count

total_changed = st.session_state["prev_total"] != total_count
alert_changed = st.session_state["prev_alert"] != alert_count
st.session_state["prev_total"] = total_count
st.session_state["prev_alert"] = alert_count

m1, m2 = st.columns(2)
with m1:
    cls_t = "metric-animated" if total_changed else ""
    st.markdown(f'<div class="{cls_t}">', unsafe_allow_html=True)
    st.metric("登録品目数", f"{total_count} 品目")
    st.markdown('</div>', unsafe_allow_html=True)
with m2:
    cls_a = "metric-animated" if alert_changed else ""
    st.markdown(f'<div class="{cls_a}">', unsafe_allow_html=True)
    st.metric("要補充・切れかけ", f"{alert_count} 件", delta=-alert_count if alert_count > 0 else None, delta_color="inverse")
    st.markdown('</div>', unsafe_allow_html=True)

st.divider()

tab_scan, tab_list, tab_buy, tab_add, tab_edit, tab_chat, tab_setting = st.tabs(["📷 スキャン", "📋 在庫一覧", "🛒 買出し", "➕ 登録", "✏️ 編集", "💬 チャット", "⚙️ 設定"])

with tab_scan:
    if not is_my_page():
        st.info("※ゲスト閲覧モードのため、スキャン登録・在庫操作はできません。")
    code = st.session_state.current_code
    if code is None:
        st.markdown("#### ① コードを読み取る")
        mode = st.radio("読み取り方法", ["カメラ", "画像を選ぶ"], horizontal=True, label_visibility="collapsed", key="scan_mode")
        found = None
        if mode.startswith("カメラ"):
            st.caption("バーコードにかざすと自動で読み取ります。")
            frame = camera_input_live(key=f"camera_{st.session_state.cam_key}")
            if frame: found = decode_first(Image.open(frame))
        else:
            up = st.file_uploader("画像選択", type=["jpg", "jpeg", "png"], label_visibility="collapsed", key=f"upload_{st.session_state.up_key}")
            if up is not None:
                found = decode_first(Image.open(up))
                if not found: st.warning("コードが見つかりませんでした。")
        
        st.divider()
        st.markdown("#### 番号を手入力する")
        typed = st.text_input("バーコード番号を入力", placeholder="例: 4901330...", key="manual_typed_code")
        if st.button("この番号で検索", type="primary", key="manual_search_btn"):
            if typed.strip():
                st.session_state.current_code = typed.strip()
                st.rerun()
        if found:
            st.session_state.current_code = found
            st.rerun()
    else:
        st.markdown("#### ② 結果")
        cursor.execute("SELECT id, name, quantity, location, expiration_date FROM items WHERE jan_code = ? AND user_id = ?", (code, viewing_uid()))
        row = cursor.fetchone()
        st.caption(f"読み取ったコード: {code}")
        
        if row:
            item_id, name, quantity, location, exp_date = row
            emoji, label = status_of(quantity)
            with st.container(border=True):
                st.markdown(f"### {name}")
                st.markdown(f"{emoji} **{label}** (残り **{quantity}** 個) / 📍 {location or '-'}")
                if exp_date: st.caption(f"⏳ 賞味期限: {exp_date}")
                
                if is_my_page():
                    b1, b2 = st.columns(2)
                    if b1.button("1つ使った", key="scan_dec", disabled=quantity == 0):
                        adjust(item_id, -1)
                        st.rerun()
                    if b2.button("+1つ補充", key="scan_inc", type="primary"):
                        adjust(item_id, 1)
                        st.rerun()
                else:
                    st.caption("※ゲストのため操作できません")
        else:
            st.warning("このコードはまだ登録されていません。")
            suggestion = ""
            if is_product_code(code):
                with st.spinner("商品名を照会中..."):
                    suggestion = fetch_product_name(code) or ""
                if suggestion: st.success(f"🔍 外部DBの候補: **{suggestion}**")

            if is_my_page():
                with st.form("scan_register_form"):
                    n_name = st.text_input("品名", value=suggestion)
                    n_qty = st.number_input("初期在庫数", min_value=0, value=1)
                    n_loc = st.selectbox("保管場所", LOCATIONS)
                    n_exp = st.date_input("賞味/消費期限 (任意)", value=None)
                    if st.form_submit_button("この内容で登録", type="primary"):
                        if not n_name.strip(): st.error("品名を入力してください。")
                        elif add_item(n_name.strip(), n_qty, n_loc, code, n_exp.strftime("%Y-%m-%d") if n_exp else None):
                            flash(f"🎉 「{n_name.strip()}」を登録しました！")
                            st.rerun()
                        else: st.error("登録に失敗しました。")

        if st.button("🔄 別のコードを読み取る", key="scan_reset"):
            st.session_state.current_code = None
            st.session_state.cam_key += 1
            st.session_state.up_key += 1
            st.rerun()

with tab_list:
    low_threshold = st.session_state["low_threshold"]
    n_total = len(rows)
    n_out = sum(1 for r in rows if r[2] == 0)
    n_low = sum(1 for r in rows if 0 < r[2] <= low_threshold)
    st.markdown(f"全 **{n_total}** 品目 | 🔴 なし **{n_out}** | 🟡 あと少し **{n_low}**")
    
    if not rows:
        st.info("まだ品目がありません。")
    else:
        all_locs = LOCATIONS + [l for l in sorted({r[3] for r in rows if r[3]}) if l not in LOCATIONS]
        f1, f2 = st.columns([3, 2])
        kw = f1.text_input("検索", placeholder="品名で検索", label_visibility="collapsed", key="stock_kw")
        loc_filter = f2.selectbox("場所", ["すべての場所"] + all_locs, label_visibility="collapsed", key="stock_loc")
        
        c_filter1, c_filter2 = st.columns(2)
        only_low = c_filter1.checkbox("要補充のみ表示", key="only_low")
        sort_exp = c_filter2.checkbox("賞味期限が近い順", key="sort_exp")

        display_rows = list(rows)
        if sort_exp: display_rows.sort(key=lambda x: x[5] if x[5] else "9999-99-99")

        today_str = date.today().strftime("%Y-%m-%d")
        shown = 0
        for item_id, name, qty, loc, jan, exp in display_rows:
            if kw and kw.lower() not in name.lower(): continue
            if loc_filter != "すべての場所" and loc != loc_filter: continue
            if only_low and qty > low_threshold: continue

            shown += 1
            emoji, label = status_of(qty)
            with st.container(key=f"row_{item_id}", border=True):
                c0, c1, c2 = st.columns(3)
                exp_tag = f" | ⏳ {exp}" if exp else ""
                if exp and exp < today_str: exp_tag += " ⚠️(期限切れ)"

                c0.markdown(f"**{name}** {emoji} {label}")
                c0.caption(f"残り {qty} 個 ({loc or '-'}){exp_tag}")
                
                if is_my_page():
                    if c1.button("-", key=f"dec_{item_id}", disabled=qty == 0):
                        adjust(item_id, -1)
                        st.rerun()
                    if c2.button("+", key=f"inc_{item_id}"):
                        adjust(item_id, 1)
                        st.rerun()
        if shown == 0: st.caption("条件に合う品目がありません。")

with tab_buy:
    low_threshold = st.session_state["low_threshold"]
    st.markdown(f"#### 🛒 買い出しメモ ({target_username}さんの残り少ない品目)")
    buy_items = [r for r in rows if r[2] <= low_threshold]
    if not buy_items:
        st.success("🎉 現在、補充が必要な商品はありません！")
    else:
        for item_id, name, qty, loc, jan, exp in buy_items:
            with st.container(border=True):
                col_a, col_b = st.columns([3, 1])
                emoji, label = status_of(qty)
                col_a.markdown(f"**{name}** ({emoji} 残り {qty} 個)")
                col_a.caption(f"📍 {loc or '場所指定なし'}")
                if is_my_page():
                    if col_b.button("🛒 補充", key=f"buy_inc_{item_id}", type="primary"):
                        adjust(item_id, 1)
                        flash(f"「{name}」を1つ補充しました")
                        st.rerun()

with tab_add:
    if not is_my_page():
        st.warning("⚠️ ゲスト閲覧中のため、商品の追加はできません。")
    else:
        st.markdown("#### 手入力で登録")
        with st.form("add_form", clear_on_submit=True):
            new_name = st.text_input("品名", placeholder="例: トイレットペーパー")
            a1, a2 = st.columns(2)
            new_qty = a1.number_input("初期在庫数", min_value=0, value=1)
            new_loc = a2.selectbox("保管場所", LOCATIONS)
            new_exp = st.date_input("賞味/消費期限 (任意)", value=None)
            new_jan = st.text_input("バーコード/QRコード番号 (任意)")
            
            if st.form_submit_button("追加する", type="primary"):
                if not new_name.strip(): st.error("品名を入力してください。")
                elif add_item(new_name.strip(), new_qty, new_loc, new_jan.strip(), new_exp.strftime("%Y-%m-%d") if new_exp else None):
                    flash(f"🎉 「{new_name.strip()}」を追加しました！")
                    st.rerun()
                else: st.error("そのバーコード番号は既に登録されています。")

        with st.expander("📄 CSVファイルから一括登録"):
            sample = "name, quantity, location, jan_code\nトイレットペーパー,3,洗面所,\n牛乳,1,冷蔵庫,\n"
            st.download_button("サンプル CSVをダウンロード", sample.encode("utf-8-sig"), file_name="sample_items.csv", mime="text/csv")
            csv_file = st.file_uploader("CSVファイルを選択", type=["csv"], key="csv_up")
            if csv_file is not None and st.button("インポートを実行", type="primary"):
                try:
                    text = csv_file.getvalue().decode("utf-8-sig", errors="ignore")
                    ok_n = skip_n = 0
                    for r in csv.DictReader(io.StringIO(text)):
                        nm = (r.get("name") or "").strip()
                        if not nm: continue
                        q = int(r.get("quantity") or 1)
                        lc = (r.get("location") or "その他").strip() or "その他"
                        jn = (r.get("jan_code") or "").strip()
                        if add_item(nm, max(q, 0), lc, jn): ok_n += 1
                        else: skip_n += 1
                    flash(f"インポート完了: 成功 {ok_n} 件")
                    st.rerun()
                except Exception as ex: st.error(f"読み込み失敗: {ex}")

with tab_edit:
    if not is_my_page():
        st.warning("⚠️ ゲスト閲覧中のため、編集・削除はできません。")
    elif not rows:
        st.info("編集できる品目がありません。")
    else:
        by_id = {r[0]: r for r in rows}
        sel = st.selectbox("編集する品目", list(by_id), format_func=lambda i: by_id[i][1], key="edit_sel")
        _i, s_name, s_qty, s_loc, s_jan, s_exp = by_id[sel]

        with st.form(f"edit_form_{sel}"):
            e_name = st.text_input("品名", value=s_name)
            e1, e2 = st.columns(2)
            e_qty = e1.number_input("在庫数", min_value=0, value=int(s_qty))
            loc_opts = LOCATIONS + ([s_loc] if s_loc and s_loc not in LOCATIONS else [])
            e_loc = e2.selectbox("保管場所", loc_opts, index=loc_opts.index(s_loc) if s_loc in loc_opts else 0)
            
            curr_exp = datetime.strptime(s_exp, "%Y-%m-%d").date() if s_exp else None
            e_exp = st.date_input("賞味/消費期限", value=curr_exp)
            e_jan = st.text_input("バーコード/QRコード番号", value=s_jan or "")

            if st.form_submit_button("保存する", type="primary"):
                try:
                    cursor.execute(
                        "UPDATE items SET name = ?, quantity = ?, location = ?, jan_code = ?, expiration_date = ? WHERE id = ? AND user_id = ?",
                        (e_name.strip() or s_name, e_qty, e_loc, e_jan.strip() or None, e_exp.strftime("%Y-%m-%d") if e_exp else None, sel, my_uid())
                    )
                    conn.commit()
                    flash("情報を更新しました")
                    st.rerun()
                except sqlite3.IntegrityError:
                    conn.rollback()
                    st.error("そのバーコード番号は既に他の商品で使用されています。")

        st.divider()
        confirm = st.checkbox("この品目を削除することを確認しました", key=f"del_ok_{sel}")
        if st.button("削除する", key=f"del_{sel}", disabled=not confirm):
            cursor.execute("DELETE FROM items WHERE id = ? AND user_id = ?", (sel, my_uid()))
            conn.commit()
            flash(f"「{s_name}」を削除しました")
            st.rerun()

#
# 💬 チャットタブ（LINE風リッチチャット：画像・スタンプ対応）
#
with tab_chat:
    st.markdown("#### 💬 メンバー間チャット (LINE風)")
    cursor.execute("SELECT id, username FROM users WHERE id != ?", (my_uid(),))
    other_users = cursor.fetchall()

    # セッションからチャット相手を引き継ぐ（アカウントページから飛んできた場合など）
    default_partner_idx = 0
    if "active_chat_partner" in st.session_state:
        for idx, u in enumerate(other_users):
            if u[0] == st.session_state["active_chat_partner"]:
                default_partner_idx = idx
                break

    if not other_users:
        st.info("他の登録ユーザーがまだいません。")
    else:
        partner_options = {u[1]: u[0] for u in other_users}
        selected_partner_name = st.selectbox("チャットする相手を選択", list(partner_options.keys()), index=default_partner_idx, key="chat_sel_partner")
        partner_id = partner_options[selected_partner_name]
        st.session_state["active_chat_partner"] = partner_id

        st.divider()
        cursor.execute("""
            SELECT sender_id, message, image_blob, created_at FROM messages 
            WHERE (sender_id = ? AND receiver_id = ?) OR (sender_id = ? AND receiver_id = ?)
            ORDER BY id ASC
        """, (my_uid(), partner_id, partner_id, my_uid()))
        messages = cursor.fetchall()

        chat_container = st.container(height=380)
        with chat_container:
            if not messages:
                st.caption(f"{selected_partner_name}さんとのメッセージはまだありません。")
            for sender_id, msg, img_blob, created_at in messages:
                is_me = (sender_id == my_uid())
                align = "right" if is_me else "left"
                bg_color = "#dcf8c6" if is_me else "#f1f0f0"
                sender_label = "あなた" if is_me else selected_partner_name
                
                st.markdown(f"<div style='text-align: {align}; margin-bottom: 10px;'><small>{sender_label} ({created_at})</small><br>", unsafe_allow_html=True)
                if msg:
                    st.markdown(f"<span style='background: {bg_color}; padding: 8px 12px; border-radius: 12px; display: inline-block; max-width: 80%; text-align: left;'>{msg}</span>", unsafe_allow_html=True)
                if img_blob:
                    try:
                        im = Image.open(io.BytesIO(img_blob))
                        st.image(im, width=200)
                    except Exception:
                        pass
                st.markdown("</div>", unsafe_allow_html=True)

        st.markdown("##### スタンプを送る")
        st_cols = st.columns(5)
        stamps = ["👍", "❤️", "🔥", "🛒", "🙏"]
        for idx, st_emoji in enumerate(stamps):
            if st_cols[idx].button(st_emoji, key=f"stamp_{st_emoji}"):
                cursor.execute(
                    "INSERT INTO messages (sender_id, receiver_id, message, created_at) VALUES (?, ?, ?, ?)",
                    (my_uid(), partner_id, f"スタンプ: {st_emoji}", datetime.now().strftime("%m/%d %H:%M"))
                )
                conn.commit()
                st.rerun()

        with st.form("chat_input_form", clear_on_submit=True):
            new_msg = st.text_input("メッセージを入力", placeholder="例: 牛乳買ってきて！", label_visibility="collapsed")
            img_upload = st.file_uploader("写真を添付 (LINE風画像送信)", type=["jpg", "jpeg", "png"], key="chat_img_up")
            if st.form_submit_button("送信", type="primary"):
                img_data = img_upload.getvalue() if img_upload else None
                if new_msg.strip() or img_data:
                    cursor.execute(
                        "INSERT INTO messages (sender_id, receiver_id, message, image_blob, created_at) VALUES (?, ?, ?, ?, ?)",
                        (my_uid(), partner_id, new_msg.strip() if new_msg else None, img_data, datetime.now().strftime("%m/%d %H:%M"))
                    )
                    conn.commit()
                    st.rerun()

#
# ⚙️ 設定タブ（共有スペース管理 ＆ 部屋の公開・合言葉入室）
#
with tab_setting:
    st.markdown(f"#### 👥 共有スペース: 現在 **{target_username}** の部屋にいるメンバー")
    
    # 共有スペースに表示するメンバーリスト（ホスト＋現在この部屋を閲覧しているゲストを想定、ここでは登録全ユーザーを表示）
    cursor.execute("SELECT id, username FROM users")
    all_room_members = cursor.fetchall()

    for m_id, m_uname in all_room_members:
        with st.container(border=True):
            col_m1, col_m2, col_m3 = st.columns([2, 1, 1])
            col_m1.markdown(f"👤 **{m_uname}** {'(あなた)' if m_id == my_uid() else ''} {'[ホスト]' if m_id == viewing_uid() else '[ゲスト/滞在中]'}")
            
            if m_id != my_uid():
                # チャット開始ボタン
                if col_m2.button("💬 チャット開始", key=f"start_chat_{m_id}"):
                    st.session_state["active_chat_partner"] = m_id
                    flash(f"{m_uname}さんとのチャットを開きました")
                    st.rerun()
                
                # キック機能（ホスト->ゲスト、ゲスト->ゲストは可能。ゲスト->ホストは「謀反」として禁止）
                is_i_am_host = is_my_page()
                is_target_host = (m_id == viewing_uid())
                
                if is_i_am_host or (not is_target_host):
                    if col_m3.button("🚪 キックする", key=f"kick_{m_id}", type="secondary"):
                        # ホストが他人をキック、またはゲストが他のゲストをキック
                        if is_target_host and not is_i_am_host:
                            st.error("⚠️ 謀反（ホストのキック）は許可されていません！")
                        else:
                            st.session_state["viewing_uid"] = my_uid() # 強制退室させて自分の部屋に戻す
                            flash(f"🔨 {m_uname}さんを部屋から退出させました。")
                            st.rerun()
                else:
                    col_m3.caption("権限なし(謀反)")

    st.divider()
    st.markdown("#### 🚪 自分の部屋の公開設定 (合言葉/パスワード)")
    cursor.execute("SELECT room_password FROM users WHERE id = ?", (my_uid(),))
    my_room_pw = cursor.fetchone()[0]

    with st.form("room_public_setting_form"):
        st.write(f"現在の公開状態: **{'🔒 パスワード設定中（公開中）' if my_room_pw else '🔓 非公開' }**")
        new_room_pw = st.text_input("新しい部屋の公開合言葉（空欄にすると非公開）", value=my_room_pw or "", type="password")
        if st.form_submit_button("公開設定を保存"):
            cursor.execute("UPDATE users SET room_password = ? WHERE id = ?", (new_room_pw.strip() or None, my_uid()))
            conn.commit()
            flash("部屋の公開設定を更新しました！")
            st.rerun()

    st.divider()
    st.markdown("#### 🔑 他の人の部屋に入る (合言葉入室)")
    cursor.execute("SELECT id, username, room_password FROM users WHERE id != ?", (my_uid(),))
    other_users = cursor.fetchall()
    
    with st.form("enter_other_room_form"):
        target_uname = st.selectbox("入室したいユーザーを選択", [u[1] for u in other_users] if other_users else ["ユーザーがいません"])
        entered_pw = st.text_input("部屋の公開パスワード（合言葉）を入力", type="password")
        
        if st.form_submit_button("部屋に入る", type="primary"):
            if not other_users:
                st.error("他のユーザーがいません。")
            else:
                cursor.execute("SELECT id, room_password FROM users WHERE username = ?", (target_uname,))
                target_info = cursor.fetchone()
                if target_info:
                    t_id, t_room_pw = target_info
                    if not t_room_pw:
                        st.error("この部屋はパスワードが設定されていないため入室できません。")
                    elif t_room_pw == entered_pw.strip():
                        st.session_state["viewing_uid"] = t_id
                        flash(f"🎉 {target_uname}さんの部屋にゲスト入室しました！")
                        st.rerun()
                    else:
                        st.error("❌ 合言葉（パスワード）が間違っています。")

    st.divider()
    st.markdown("#### 🎨 アプリのカスタマイズ ")
    with st.form("custom_setting_form"):
        new_title = st.text_input("アプリのタイトル", value=st.session_state["app_title"])
        new_emoji = st.text_input("タイトルのアイコン絵文字", value=st.session_state["app_emoji"])
        new_thresh = st.number_input("「あと少し」と判定する残り個数の基準", min_value=1, value=st.session_state["low_threshold"], step=1)
        if st.form_submit_button("設定を反映する", type="primary"):
            st.session_state["app_title"] = new_title.strip() or "うちのストック"
            st.session_state["app_emoji"] = new_emoji.strip() or "📦"
            st.session_state["low_threshold"] = new_thresh
            flash("設定を更新しました！")
            st.rerun()

    if is_my_page():
        st.divider()
        st.markdown("#### 👤 プロフィール・アイコン変更")
        with st.form("avatar_form"):
            uploaded_avatar = st.file_uploader("新しいアバター画像を選択 (JPG / PNG)", type=["jpg", "jpeg", "png"])
            if st.form_submit_button("アイコンを更新"):
                if uploaded_avatar is not None:
                    blob_data = uploaded_avatar.getvalue()
                    cursor.execute("UPDATE users SET avatar_blob = ? WHERE id = ?", (blob_data, my_uid()))
                    conn.commit()
                    st.session_state["avatar_blob"] = blob_data
                    flash("プロフィールアイコンを更新しました！")
                    st.rerun()

        st.divider()
        st.markdown("#### 🔑 パスワード変更")
        with st.form("password_change_form"):
            old_pw = st.text_input("現在のパスワード", type="password")
            new_pw = st.text_input("新しいパスワード (8文字以上)", type="password")
            new_pw_confirm = st.text_input("新しいパスワード (確認)", type="password")
            if st.form_submit_button("パスワードを変更"):
                cursor.execute("SELECT salt, pw_hash FROM users WHERE id = ?", (my_uid(),))
                row = cursor.fetchone()
                if row:
                    saved_salt = bytes.fromhex(row[0])
                    if hmac.compare_digest(hash_pw(old_pw, saved_salt), row[1]):
                        if len(new_pw) < 8: st.error("8文字以上にしてください。")
                        elif new_pw != new_pw_confirm: st.error("確認用パスワードが一致しません。")
                        else:
                            new_salt = os.urandom(16)
                            new_hash = hash_pw(new_pw, new_salt)
                            cursor.execute("UPDATE users SET salt = ?, pw_hash = ? WHERE id = ?", (new_salt.hex(), new_hash, my_uid()))
                            conn.commit()
                            flash("パスワードを変更しました！")
                            st.rerun()
                    else: st.error("現在のパスワードが間違っています。")

        st.divider()
        st.markdown("#### 📱 LINE 通知設定")
        with st.form("line_setting_form"):
            line_token_input = st.text_input("LINE Notify Token", value=st.session_state.get("line_token") or "", type="password", placeholder="アクセストークンを入力")
            if st.form_submit_button("LINE連携を保存"):
                cursor.execute("UPDATE users SET line_token = ? WHERE id = ?", (line_token_input.strip() or None, my_uid()))
                conn.commit()
                st.session_state["line_token"] = line_token_input.strip()
                flash("LINE通知設定を保存しました")
                st.rerun()
