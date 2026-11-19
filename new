import hashlib
import hmac
import os
import sqlite3
from datetime import datetime
import streamlit as st

DB_PATH = "uchi_stock.db"
PBKDF2_ITERATIONS = 200_000
MAX_IMAGE_BYTES = 2 * 1024 * 1024  # 2MB


def get_connection() -> sqlite3.Connection:
    conn = sqlite3.connect(DB_PATH, check_same_thread=False)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON;")
    return conn


def init_db() -> None:
    conn = get_connection()
    try:
        cur = conn.cursor()
        cur.execute(
            """
            CREATE TABLE IF NOT EXISTS users (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                username TEXT UNIQUE COLLATE NOCASE NOT NULL,
                salt TEXT NOT NULL,
                pw_hash TEXT NOT NULL,
                line_token TEXT,
                avatar_blob BLOB,
                room_password TEXT,
                created_at TEXT NOT NULL
            );
            """
        )
        cur.execute(
            """
            CREATE TABLE IF NOT EXISTS items (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER NOT NULL,
                name TEXT NOT NULL,
                quantity INTEGER NOT NULL DEFAULT 1,
                location TEXT,
                jan_code TEXT,
                expiration_date TEXT,
                FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE CASCADE
            );
            """
        )
        cur.execute(
            """
            CREATE INDEX IF NOT EXISTS idx_items_user_jan
            ON items(user_id, jan_code);
            """
        )
        cur.execute(
            """
            CREATE TABLE IF NOT EXISTS locations (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER NOT NULL,
                name TEXT NOT NULL,
                UNIQUE(user_id, name),
                FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE CASCADE
            );
            """
        )
        cur.execute(
            """
            CREATE TABLE IF NOT EXISTS room_presence (
                user_id INTEGER PRIMARY KEY,
                host_id INTEGER NOT NULL,
                joined_at TEXT NOT NULL,
                FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE CASCADE,
                FOREIGN KEY (host_id) REFERENCES users(id) ON DELETE CASCADE
            );
            """
        )
        cur.execute(
            """
            CREATE TABLE IF NOT EXISTS messages (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                sender_id INTEGER NOT NULL,
                receiver_id INTEGER NOT NULL,
                message TEXT NOT NULL,
                image_blob BLOB,
                reply_to_id INTEGER,
                is_deleted INTEGER NOT NULL DEFAULT 0,
                is_read INTEGER NOT NULL DEFAULT 0,
                created_at TEXT NOT NULL,
                FOREIGN KEY (sender_id) REFERENCES users(id) ON DELETE CASCADE,
                FOREIGN KEY (receiver_id) REFERENCES users(id) ON DELETE CASCADE,
                FOREIGN KEY (reply_to_id) REFERENCES messages(id) ON DELETE SET NULL
            );
            """
        )
        # 既存DBに is_read 列がない場合のための安全なマイグレーション
        cols = [r["name"] for r in cur.execute("PRAGMA table_info(messages);").fetchall()]
        if "is_read" not in cols:
            cur.execute("ALTER TABLE messages ADD COLUMN is_read INTEGER NOT NULL DEFAULT 0;")
        conn.commit()
    finally:
        conn.close()


def hash_secret(secret: str, salt_hex: str | None = None) -> tuple[str, str]:
    if not secret:
        return "", ""
    salt_bytes = bytes.fromhex(salt_hex) if salt_hex else os.urandom(16)
    digest = hashlib.pbkdf2_hmac(
        "sha256",
        secret.encode("utf-8"),
        salt_bytes,
        PBKDF2_ITERATIONS,
    )
    return salt_bytes.hex(), digest.hex()


def verify_secret(secret: str, salt_hex: str, expected_hash_hex: str) -> bool:
    if not secret or not salt_hex or not expected_hash_hex:
        return False
    _, actual_hash_hex = hash_secret(secret, salt_hex)
    return hmac.compare_digest(actual_hash_hex, expected_hash_hex)


def register_user(username: str, password: str, room_password: str = "") -> tuple[bool, str]:
    clean_name = username.strip()
    if len(clean_name) < 2 or len(password) < 4:
        return False, "ユーザー名は2文字以上、パスワードは4文字以上で入力してください。"

    salt_hex, pw_hash_hex = hash_secret(password)
    room_pw_hash = ""
    if room_password.strip():
        _, room_pw_hash = hash_secret(room_password.strip(), salt_hex)

    now_str = datetime.now().isoformat(timespec="seconds")
    conn = get_connection()
    try:
        conn.execute(
            """
            INSERT INTO users (username, salt, pw_hash, room_password, created_at)
            VALUES (?, ?, ?, ?, ?);
            """,
            (clean_name, salt_hex, pw_hash_hex, room_pw_hash or None, now_str),
        )
        conn.commit()
        return True, "アカウントを作成しました。ログインしてください。"
    except sqlite3.IntegrityError:
        return False, "そのユーザー名はすでに使われています。"
    finally:
        conn.close()


def authenticate_user(username: str, password: str) -> sqlite3.Row | None:
    clean_name = username.strip()
    if not clean_name or not password:
        return None
    conn = get_connection()
    try:
        row = conn.execute(
            "SELECT * FROM users WHERE username = ? COLLATE NOCASE;",
            (clean_name,),
        ).fetchone()
        if row and verify_secret(password, row["salt"], row["pw_hash"]):
            return row
        return None
    finally:
        conn.close()


def update_room_password(user_id: int, new_room_password: str) -> None:
    conn = get_connection()
    try:
        user = conn.execute("SELECT salt FROM users WHERE id = ?;", (user_id,)).fetchone()
        if not user:
            return
        if new_room_password.strip():
            _, room_pw_hash = hash_secret(new_room_password.strip(), user["salt"])
        else:
            room_pw_hash = None
        conn.execute(
            "UPDATE users SET room_password = ? WHERE id = ?;",
            (room_pw_hash, user_id),
        )
        conn.commit()
    finally:
        conn.close()


def join_room(user_id: int, host_username: str, room_password_input: str) -> tuple[bool, str]:
    clean_host = host_username.strip()
    if not clean_host:
        return False, "接続先のホストユーザー名を入力してください。"

    conn = get_connection()
    try:
        host = conn.execute(
            "SELECT id, username, salt, room_password FROM users WHERE username = ? COLLATE NOCASE;",
            (clean_host,),
        ).fetchone()
        if not host:
            return False, "指定されたホストユーザーが見つかりません。"

        if host["id"] == user_id:
            conn.execute("DELETE FROM room_presence WHERE user_id = ?;", (user_id,))
            conn.commit()
            return True, "自分のルーム（単独モード）に戻りました。"

        # ホストにルームパスワードが設定されている場合は照合する
        if host["room_password"]:
            if not verify_secret(room_password_input, host["salt"], host["room_password"]):
                return False, "ルームパスワードが一致しません。"
        else:
            return False, "このホストはルーム共有用のパスワードを設定していません。"

        now_str = datetime.now().isoformat(timespec="seconds")
        conn.execute(
            """
            INSERT INTO room_presence (user_id, host_id, joined_at)
            VALUES (?, ?, ?)
            ON CONFLICT(user_id) DO UPDATE SET
                host_id = excluded.host_id,
                joined_at = excluded.joined_at;
            """,
            (user_id, host["id"], now_str),
        )
        conn.commit()
        return True, f"{host['username']} さんのルームに接続しました。"
    finally:
        conn.close()


def leave_room(user_id: int) -> None:
    conn = get_connection()
    try:
        conn.execute("DELETE FROM room_presence WHERE user_id = ?;", (user_id,))
        conn.commit()
    finally:
        conn.close()


def get_active_host_id(user_id: int) -> int:
    """現在つながっているルームのホストID（未参加なら自分自身）を返す。"""
    conn = get_connection()
    try:
        row = conn.execute(
            "SELECT host_id FROM room_presence WHERE user_id = ?;",
            (user_id,),
        ).fetchone()
        return int(row["host_id"]) if row else user_id
    finally:
        conn.close()


def get_connected_user_ids(user_id: int) -> list[int]:
    """共有対象として許可されたユーザーID一覧（自分＋同一ルーム参加者）を返す。"""
    host_id = get_active_host_id(user_id)
    conn = get_connection()
    try:
        rows = conn.execute(
            """
            SELECT user_id FROM room_presence WHERE host_id = ?
            UNION
            SELECT host_id AS user_id FROM room_presence WHERE host_id = ?
            UNION
            SELECT ? AS user_id;
            """,
            (host_id, host_id, user_id),
        ).fetchall()
        ids = {int(r["user_id"]) for r in rows}
        ids.add(user_id)
        return sorted(ids)
    finally:
        conn.close()


def get_username_map() -> dict[int, str]:
    conn = get_connection()
    try:
        rows = conn.execute("SELECT id, username FROM users;").fetchall()
        return {int(r["id"]): str(r["username"]) for r in rows}
    finally:
        conn.close()


def send_message(
    sender_id: int,
    receiver_id: int,
    message: str,
    image_bytes: bytes | None = None,
    reply_to_id: int | None = None,
) -> tuple[bool, str]:
    allowed_ids = set(get_connected_user_ids(sender_id))
    if receiver_id not in allowed_ids or receiver_id == sender_id:
        return False, "同一ルームでつながっている相手のみ送信できます。"

    clean_msg = message.strip()
    if not clean_msg and not image_bytes:
        return False, "メッセージまたは画像を入力してください。"

    if image_bytes and len(image_bytes) > MAX_IMAGE_BYTES:
        return False, "画像サイズは2MB以下にしてください。"

    conn = get_connection()
    try:
        valid_reply_id = None
        if reply_to_id is not None:
            ref = conn.execute(
                """
                SELECT id FROM messages
                WHERE id = ?
                  AND is_deleted = 0
                  AND ((sender_id = ? AND receiver_id = ?) OR (sender_id = ? AND receiver_id = ?));
                """,
                (reply_to_id, sender_id, receiver_id, receiver_id, sender_id),
            ).fetchone()
            if ref:
                valid_reply_id = int(ref["id"])

        now_str = datetime.now().isoformat(timespec="seconds")
        conn.execute(
            """
            INSERT INTO messages (
                sender_id, receiver_id, message, image_blob, reply_to_id, is_deleted, is_read, created_at
            )
            VALUES (?, ?, ?, ?, ?, 0, 0, ?);
            """,
            (sender_id, receiver_id, clean_msg, image_bytes, valid_reply_id, now_str),
        )
        conn.commit()
        return True, "送信しました。"
    finally:
        conn.close()


def fetch_conversation(current_user_id: int, peer_id: int) -> list[sqlite3.Row]:
    conn = get_connection()
    try:
        # 相手から自分宛ての未読メッセージを既読化
        conn.execute(
            """
            UPDATE messages
            SET is_read = 1
            WHERE sender_id = ? AND receiver_id = ? AND is_read = 0;
            """,
            (peer_id, current_user_id),
        )
        conn.commit()

        rows = conn.execute(
            """
            SELECT * FROM messages
            WHERE is_deleted = 0
              AND ((sender_id = ? AND receiver_id = ?) OR (sender_id = ? AND receiver_id = ?))
            ORDER BY id ASC;
            """,
            (current_user_id, peer_id, peer_id, current_user_id),
        ).fetchall()
        return rows
    finally:
        conn.close()


def soft_delete_message(current_user_id: int, message_id: int) -> None:
    conn = get_connection()
    try:
        conn.execute(
            "UPDATE messages SET is_deleted = 1 WHERE id = ? AND sender_id = ?;",
            (message_id, current_user_id),
        )
        conn.commit()
    finally:
        conn.close()


def add_location(user_id: int, name: str) -> tuple[bool, str]:
    target_owner_id = get_active_host_id(user_id)
    clean_name = name.strip()
    if not clean_name:
        return False, "保管場所名を入力してください。"
    conn = get_connection()
    try:
        conn.execute(
            "INSERT OR IGNORE INTO locations (user_id, name) VALUES (?, ?);",
            (target_owner_id, clean_name),
        )
        conn.commit()
        return True, f"保管場所「{clean_name}」を追加しました。"
    finally:
        conn.close()


def list_locations(user_id: int) -> list[str]:
    allowed_ids = get_connected_user_ids(user_id)
    placeholders = ",".join("?" for _ in allowed_ids)
    conn = get_connection()
    try:
        rows = conn.execute(
            f"SELECT DISTINCT name FROM locations WHERE user_id IN ({placeholders}) ORDER BY name ASC;",
            allowed_ids,
        ).fetchall()
        return [str(r["name"]) for r in rows]
    finally:
        conn.close()


def add_item(
    user_id: int,
    name: str,
    quantity: int,
    location: str,
    jan_code: str,
    expiration_date: str,
) -> tuple[bool, str]:
    clean_name = name.strip()
    if not clean_name:
        return False, "商品名を入力してください。"
    owner_id = get_active_host_id(user_id)
    conn = get_connection()
    try:
        conn.execute(
            """
            INSERT INTO items (user_id, name, quantity, location, jan_code, expiration_date)
            VALUES (?, ?, ?, ?, ?, ?);
            """,
            (
                owner_id,
                clean_name,
                max(0, int(quantity)),
                location.strip() or None,
                jan_code.strip() or None,
                expiration_date.strip() or None,
            ),
        )
        conn.commit()
        return True, f"「{clean_name}」を登録しました。"
    finally:
        conn.close()


def list_items(user_id: int) -> list[sqlite3.Row]:
    allowed_ids = get_connected_user_ids(user_id)
    placeholders = ",".join("?" for _ in allowed_ids)
    conn = get_connection()
    try:
        return conn.execute(
            f"SELECT * FROM items WHERE user_id IN ({placeholders}) ORDER BY id DESC;",
            allowed_ids,
        ).fetchall()
    finally:
        conn.close()


def adjust_item_quantity(user_id: int, item_id: int, delta: int) -> None:
    allowed_ids = get_connected_user_ids(user_id)
    placeholders = ",".join("?" for _ in allowed_ids)
    conn = get_connection()
    try:
        row = conn.execute(
            f"SELECT quantity FROM items WHERE id = ? AND user_id IN ({placeholders});",
            (item_id, *allowed_ids),
        ).fetchone()
        if not row:
            return
        new_qty = max(0, int(row["quantity"]) + delta)
        conn.execute(
            f"UPDATE items SET quantity = ? WHERE id = ? AND user_id IN ({placeholders});",
            (new_qty, item_id, *allowed_ids),
        )
        conn.commit()
    finally:
        conn.close()


def render_auth_ui() -> None:
    st.title("うちのストック｜アカウント連携・共有")
    tab_login, tab_register = st.tabs(["ログイン", "新規アカウント作成"])

    with tab_login:
        with st.form("login_form"):
            username = st.text_input("ユーザー名")
            password = st.text_input("パスワード", type="password")
            submitted = st.form_submit_button("ログイン")
            if submitted:
                user = authenticate_user(username, password)
                if user:
                    st.session_state["current_user_id"] = int(user["id"])
                    st.session_state["current_username"] = str(user["username"])
                    st.rerun()
                else:
                    st.error("ユーザー名またはパスワードが正しくありません。")

    with tab_register:
        with st.form("register_form"):
            new_username = st.text_input("ユーザー名（2文字以上）")
            new_password = st.text_input("パスワード（4文字以上）", type="password")
            room_pw = st.text_input(
                "自分のルーム共有パスワード（任意・他アカウントを招待／接続させる場合）",
                type="password",
            )
            reg_submitted = st.form_submit_button("登録する")
            if reg_submitted:
                ok, msg = register_user(new_username, new_password, room_pw)
                if ok:
                    st.success(msg)
                else:
                    st.error(msg)


def render_main_ui(current_user_id: int, current_username: str) -> None:
    user_map = get_username_map()
    active_host_id = get_active_host_id(current_user_id)
    connected_ids = get_connected_user_ids(current_user_id)

    with st.sidebar:
        st.markdown(f"**ログイン中:** {current_username} (ID: {current_user_id})")
        host_name = user_map.get(active_host_id, "不明")
        st.markdown(f"**現在のルーム:** {host_name}")
        st.caption("共有中メンバー: " + ", ".join(user_map.get(uid, str(uid)) for uid in connected_ids))

        if st.button("ログアウト", use_container_width=True):
            st.session_state.pop("current_user_id", None)
            st.session_state.pop("current_username", None)
            st.rerun()

        st.divider()
        st.subheader("自分のルーム共有設定")
        with st.form("room_pw_form"):
            new_room_pw = st.text_input("ルーム共有パスワード（空欄で解除）", type="password")
            if st.form_submit_button("保存"):
                update_room_password(current_user_id, new_room_pw)
                st.success("ルーム共有パスワードを更新しました。")

    st.title("うちのストック")
    tab_connect, tab_stock, tab_chat = st.tabs(["ルーム接続", "在庫・保管場所", "ルーム内チャット"])

    # 1. ルーム接続（アカウント同士のつながり）
    with tab_connect:
        st.subheader("他のアカウントとルームでつながる")
        with st.form("join_room_form"):
            host_input = st.text_input("接続先のホストユーザー名")
            room_pw_input = st.text_input("相手のルーム共有パスワード", type="password")
            col1, col2 = st.columns(2)
            join_btn = col1.form_submit_button("ルームに接続")
            leave_btn = col2.form_submit_button("ルームから退出")

            if join_btn:
                ok, msg = join_room(current_user_id, host_input, room_pw_input)
                if ok:
                    st.success(msg)
                    st.rerun()
                else:
                    st.error(msg)

            if leave_btn:
                leave_room(current_user_id)
                st.info("ルームから退出しました。")
                st.rerun()

    # 2. 在庫・保管場所共有
    with tab_stock:
        st.subheader("保管場所の追加")
        with st.form("add_loc_form"):
            loc_name = st.text_input("保管場所名（例：冷蔵庫、パントリー）")
            if st.form_submit_button("保管場所を追加"):
                ok, msg = add_location(current_user_id, loc_name)
                (st.success if ok else st.error)(msg)
                if ok:
                    st.rerun()

        locations = list_locations(current_user_id)

        st.subheader("在庫の登録")
        with st.form("add_item_form"):
            item_name = st.text_input("商品名")
            qty = st.number_input("数量", min_value=0, value=1, step=1)
            selected_loc = st.selectbox("保管場所", options=[""] + locations)
            jan = st.text_input("JANコード（任意）")
            exp_date = st.text_input("賞味・消費期限（例：2026-12-31、任意）")
            if st.form_submit_button("在庫を追加"):
                ok, msg = add_item(current_user_id, item_name, int(qty), selected_loc, jan, exp_date)
                (st.success if ok else st.error)(msg)
                if ok:
                    st.rerun()

        st.subheader("共有中の在庫一覧")
        items = list_items(current_user_id)
        if not items:
            st.info("登録されている在庫はありません。")
        else:
            for item in items:
                owner = user_map.get(int(item["user_id"]), "不明")
                c1, c2, c3, c4 = st.columns([4, 2, 1, 1])
                c1.write(
                    f"**{item['name']}**（保管: {item['location'] or '未設定'} / 期限: {item['expiration_date'] or '-'} / 作成: {owner}）"
                )
                c2.write(f"数量: **{item['quantity']}**")
                if c3.button("＋", key=f"inc_{item['id']}"):
                    adjust_item_quantity(current_user_id, int(item["id"]), 1)
                    st.rerun()
                if c4.button("－", key=f"dec_{item['id']}"):
                    adjust_item_quantity(current_user_id, int(item["id"]), -1)
                    st.rerun()

    # 3. メッセージ送受信
    with tab_chat:
        peers = [uid for uid in connected_ids if uid != current_user_id]
        if not peers:
            st.info("チャットするには「ルーム接続」タブから他のアカウントとルームでつながってください。")
        else:
            peer_id = st.selectbox(
                "送信相手（同一ルーム内）",
                options=peers,
                format_func=lambda uid: f"{user_map.get(uid, uid)} (ID: {uid})",
            )
            conv_rows = fetch_conversation(current_user_id, int(peer_id))
            msg_lookup = {int(r["id"]): r for r in conv_rows}

            for m in conv_rows:
                sender_name = user_map.get(int(m["sender_id"]), "不明")
                prefix = ""
                if m["reply_to_id"] and int(m["reply_to_id"]) in msg_lookup:
                    ref_text = msg_lookup[int(m["reply_to_id"])]["message"] or "[画像]"
                    prefix = f"> 返信先: {ref_text[:30]}\n\n"

                col_m, col_d = st.columns([8, 1])
                with col_m:
                    st.markdown(f"**{sender_name}** ({m['created_at']})\n\n{prefix}{m['message']}")
                    if m["image_blob"]:
                        st.image(m["image_blob"], width=240)
                with col_d:
                    if int(m["sender_id"]) == current_user_id:
                        if st.button("削除", key=f"del_msg_{m['id']}"):
                            soft_delete_message(current_user_id, int(m["id"]))
                            st.rerun()

            st.divider()
            reply_options = [None] + [int(r["id"]) for r in conv_rows]
            with st.form("send_msg_form"):
                msg_text = st.text_area("メッセージ")
                uploaded_img = st.file_uploader("画像添付（任意・2MBまで）", type=["png", "jpg", "jpeg", "webp"])
                reply_target = st.selectbox(
                    "返信対象（任意）",
                    options=reply_options,
                    format_func=lambda mid: "返信しない"
                    if mid is None
                    else f"#{mid}: {(msg_lookup[mid]['message'] or '[画像]')[:25]}",
                )
                if st.form_submit_button("送信"):
                    img_bytes = uploaded_img.getvalue() if uploaded_img is not None else None
                    ok, status_msg = send_message(
                        sender_id=current_user_id,
                        receiver_id=int(peer_id),
                        message=msg_text,
                        image_bytes=img_bytes,
                        reply_to_id=reply_target,
                    )
                    (st.success if ok else st.error)(status_msg)
                    if ok:
                        st.rerun()


def main() -> None:
    st.set_page_config(page_title="うちのストック", layout="wide")
    init_db()

    current_user_id = st.session_state.get("current_user_id")
    current_username = st.session_state.get("current_username")
    if not current_user_id or not current_username:
        render_auth_ui()
    else:
        render_main_ui(int(current_user_id), str(current_username))


if __name__ == "__main__":
    main()
