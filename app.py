import sqlite3
import streamlit as st

# --- データベース初期化 ---
conn = sqlite3.connect("inventory.db", check_same_thread=False)
cursor = conn.cursor()
cursor.execute(
    """
    CREATE TABLE IF NOT EXISTS items (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        name TEXT NOT NULL,
        quantity INTEGER NOT NULL,
        location TEXT
    )
"""
)
conn.commit()

# --- アプリの画面設定 ---
st.set_page_config(page_title="うちのストック", page_icon="📦")
st.title("📦 うちのストック（家庭内在庫管理）")

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
                "INSERT INTO items (name, quantity, location) VALUES (?, ?, ?)",
                (new_name, new_qty, new_loc),
            )
            conn.commit()
            st.success(f"「{new_name}」を追加しました！")
            st.rerun()

# --- 2. 在庫一覧・増減・編集・削除機能 ---
st.subheader("📋 在庫一覧")

cursor.execute("SELECT id, name, quantity, location FROM items")
items = cursor.fetchall()

if not items:
    st.info("登録されている品目がありません。上のフォームから追加してください。")
else:
    for item in items:
        item_id, name, quantity, location = item

        # 在庫行の表示
        col1, col2, col3, col4 = st.columns([3, 2, 2, 2])

        with col1:
            if quantity == 0:
                st.markdown(f"⚠️ **{name}** （買い出しが必要！）")
            else:
                st.markdown(f"**{name}** （{location}）")

        with col2:
            st.write(f"残り: **{quantity}** 個")

        # 個数を減らすボタン
        with col3:
            if st.button("➖ 1減らす", key=f"dec_{item_id}"):
                if quantity > 0:
                    cursor.execute(
                        "UPDATE items SET quantity = quantity - 1 WHERE id = ?",
                        (item_id,),
                    )
                    conn.commit()
                    st.rerun()

        # 個数を増やすボタン
        with col4:
            if st.button("➕ 1増やす", key=f"inc_{item_id}"):
                cursor.execute(
                    "UPDATE items SET quantity = quantity + 1 WHERE id = ?",
                    (item_id,),
                )
                conn.commit()
                st.rerun()

        # --- 編集・削除アコーディオン ---
        with st.expander(f"✏️️ 「{name}」の情報を修正・削除する"):
            # 修正フォーム
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
                        "UPDATE items SET name = ?, quantity = ?, location = ? WHERE id = ?",
                        (edit_name, edit_qty, edit_loc, item_id),
                    )
                    conn.commit()
                    st.success("情報を更新しました！")
                    st.rerun()

            # 削除機能
            if st.button("🗑️ この品目を削除する", key=f"del_{item_id}"):
                cursor.execute("DELETE FROM items WHERE id = ?", (item_id,))
                conn.commit()
                st.warning(f"「{name}」を削除しました。")
                st.rerun()

        st.divider()