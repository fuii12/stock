import sqlite3
import streamlit as st

# --- アプリの画面設定 ---
st.set_page_config(page_title="うちのストック", page_icon="📦")
st.title("📦 うちのストック（家庭内在庫管理）")

# --- ユーザー名の管理（Session State版） ---
if "username" not in st.session_state:
    st.session_state.username = ""

if not st.session_state.username:
    st.info("👋 はじめての方へ：あなたの名前（またはニックネーム）を入力してください。")
    with st.form("login_form"):
        input_name = st.text_input("お名前")
        submitted = st.form_submit_button("はじめる")
        if submitted and input_name:
            st.session_state.username = input_name
            st.rerun()
    st.stop()  # 名前が入力されるまでここで処理をストップ

# ログイン中のユーザー名表示と変更ボタン
col_user1, col_user2 = st.columns([4, 1])
with col_user1:
    st.success(f"ログイン中: **{st.session_state.username}** さん")
with col_user2:
    if st.button("名前変更"):
        st.session_state.username = ""
        st.rerun()

st.divider()

# --- データベース初期化 ---
conn = sqlite3.connect("inventory.db", check_same_thread=False)
cursor = conn.cursor()
cursor.execute(
    """
    CREATE TABLE IF NOT EXISTS items (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        name TEXT NOT NULL,
        quantity INTEGER NOT NULL,
        location TEXT,
        updated_by TEXT
    )
"""
)
conn.commit()

# --- 1. 新しいアイテムの追加機能 ---
with st.expander("➕ 新しい品目を登録する"):
    with st.form("add_form", clear_on_submit=True):
        new_name = st.text_input("品名（例: トイレットペーパー）")
        new_qty = st.number_input("初期在庫数", min_value=0, value=1)
        new_loc = st.selectbox(
            "保管場所", ["パントリー", "冷蔵庫", "洗面所", "その他"]
        )
        submitted = st.form_submit_button("追加")

        if submitted and new_name:
            cursor.execute(
                "INSERT INTO items (name, quantity, location, updated_by) VALUES (?, ?, ?, ?)",
                (new_name, new_qty, new_loc, st.session_state.username),
            )
            conn.commit()
            st.success(f"「{new_name}」を追加しました！")
            st.rerun()

# --- 2. 在庫一覧・増減・編集・削除機能 ---
st.subheader("📋 在庫一覧")

cursor.execute(
    "SELECT id, name, quantity, location, updated_by FROM items"
)
items = cursor.fetchall()

if not items:
    st.info("登録されている品目がありません。上のフォームから追加してください。")
else:
    for item in items:
        item_id, name, quantity, location, updated_by = item

        # 在庫行の表示
        col1, col2, col3, col4 = st.columns([3, 2, 2, 2])

        with col1:
            if quantity == 0:
                st.markdown(f"⚠️ **{name}** （買い出しが必要！）")
            else:
                st.markdown(f"**{name}** （{location}）")
            if updated_by:
                st.caption(f"最終更新: {updated_by}さん")

        with col2:
            st.write(f"残り: **{quantity}** 個")

        # 個数を減らすボタン
        with col3:
            if st.button("➖ 1減らす", key=f"dec_{item_id}"):
                if quantity > 0:
                    cursor.execute(
                        "UPDATE items SET quantity = quantity - 1, updated_by = ? WHERE id = ?",
                        (st.session_state.username, item_id),
                    )
                    conn.commit()
                    st.rerun()

        # 個数を増やすボタン
        with col4:
            if st.button("➕ 1増やす", key=f"inc_{item_id}"):
                cursor.execute(
                    "UPDATE items SET quantity = quantity + 1, updated_by = ? WHERE id = ?",
                    (st.session_state.username, item_id),
                )
                conn.commit()
                st.rerun()

        # --- 編集・削除アコーディオン ---
        with st.expander(f"✏ 「{name}」の情報を修正・削除する"):
            with st.form(key=f"edit_form_{item_id}"):
                edit_name = st.text_input("品名", value=name)
                edit_qty = st.number_input(
                    "在庫数", min_value=0, value=int(quantity)
                )
                locations = ["パントリー", "冷蔵庫", "洗面所", "その他"]
                loc_index = (
                    locations.index(location) if location in locations else 3
                )
                edit_loc = st.selectbox(
                    "保管場所", locations, index=loc_index
                )

                update_btn = st.form_submit_button("内容を保存する")

                if update_btn:
                    cursor.execute(
                        "UPDATE items SET name = ?, quantity = ?, location = ?, updated_by = ? WHERE id = ?",
                        (
                            edit_name,
                            edit_qty,
                            edit_loc,
                            st.session_state.username,
                            item_id,
                        ),
                    )
                    conn.commit()
                    st.success("情報を更新しました！")
                    st.rerun()

            if st.button("🗑️ この品目を削除する", key=f"del_{item_id}"):
                cursor.execute("DELETE FROM items WHERE id = ?", (item_id,))
                conn.commit()
                st.warning(f"「{name}」を削除しました。")
                st.rerun()

        st.divider()
