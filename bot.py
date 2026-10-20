import asyncio
import sqlite3
import html
import io
from datetime import datetime
from aiogram import Bot, Dispatcher
from aiogram.filters import CommandStart
from aiogram.types import (
    Message,
    BusinessMessagesDeleted,
    BusinessConnection,
    BufferedInputFile,
)
from aiogram.enums import ParseMode

# ================= НАСТРОЙКИ =================
BOT_TOKEN = "8812901781:AAHiNIf7zKfJ2F5I-ZlgFOUwoT53KosdN8Q"
# =============================================

bot = Bot(token=BOT_TOKEN)
dp = Dispatcher()

conn = sqlite3.connect("multiuser_business_cache.db")
cursor = conn.cursor()

cursor.execute("""
CREATE TABLE IF NOT EXISTS connections (
    connection_id TEXT PRIMARY KEY,
    owner_id INTEGER,
    owner_name TEXT
)
""")

cursor.execute("""
CREATE TABLE IF NOT EXISTS messages (
    connection_id TEXT,
    chat_id INTEGER,
    message_id INTEGER,
    sender_id INTEGER,
    sender_name TEXT,
    sender_username TEXT,
    content_type TEXT,
    text TEXT,
    file_id TEXT,
    PRIMARY KEY (connection_id, chat_id, message_id)
)
""")
conn.commit()


def log(action: str):
    now = datetime.now().strftime("%H:%M:%S")
    print(f"[{now}] {action}")


async def get_owner_id(connection_id: str) -> int | None:
    cursor.execute("SELECT owner_id FROM connections WHERE connection_id = ?", (connection_id,))
    row = cursor.fetchone()
    if row:
        return row[0]

    try:
        conn_info = await bot.get_business_connection(connection_id)
        owner_id = conn_info.user.id
        owner_name = conn_info.user.full_name
        cursor.execute(
            "INSERT OR REPLACE INTO connections (connection_id, owner_id, owner_name) VALUES (?, ?, ?)",
            (connection_id, owner_id, owner_name)
        )
        conn.commit()
        return owner_id
    except Exception as e:
        log(f"⚠️ Ошибка получения владельца: {e}")
        return None


def extract_content(message: Message) -> tuple[str, str, str | None]:
    text = message.text or message.caption or ""
    if message.photo:
        return "photo", text, message.photo[-1].file_id
    elif message.video:
        return "video", text, message.video.file_id
    elif message.voice:
        return "voice", text, message.voice.file_id
    elif message.video_note:
        return "video_note", text, message.video_note.file_id
    elif message.document:
        return "document", text, message.document.file_id
    elif message.audio:
        return "audio", text, message.audio.file_id
    elif message.sticker:
        return "sticker", text, message.sticker.file_id
    elif message.animation:
        return "animation", text, message.animation.file_id
    else:
        return "text", text, None


def format_sender(name: str, username: str | None) -> str:
    safe_name = html.escape(name or "Без имени")
    if username:
        return f"{safe_name} (@{html.escape(username)})"
    return safe_name


async def download_and_send_media(target_user_id: int, header: str, content_type: str, text: str, file_id: str):
    """
    Скачивает файл (включая сгорающие фото/видео/кружочки) в память
    и отправляет его заново, обходя запрет на пересылку защищенного file_id.
    """
    safe_text = html.escape(text) if text else ""
    caption = f"{header}\n\n💬 <b>Подпись:</b>\n<blockquote>{safe_text}</blockquote>" if safe_text else header

    # Скачиваем файл с серверов Telegram в оперативную память (BytesIO)
    buffer = io.BytesIO()
    await bot.download(file_id, destination=buffer)
    file_bytes = buffer.getvalue()

    if content_type == "photo":
        input_file = BufferedInputFile(file_bytes, filename="secret_photo.jpg")
        await bot.send_photo(target_user_id, input_file, caption=caption, parse_mode=ParseMode.HTML)
    elif content_type == "video":
        input_file = BufferedInputFile(file_bytes, filename="secret_video.mp4")
        await bot.send_video(target_user_id, input_file, caption=caption, parse_mode=ParseMode.HTML)
    elif content_type == "voice":
        input_file = BufferedInputFile(file_bytes, filename="secret_voice.ogg")
        await bot.send_voice(target_user_id, input_file, caption=caption, parse_mode=ParseMode.HTML)
    elif content_type == "video_note":
        input_file = BufferedInputFile(file_bytes, filename="secret_circle.mp4")
        await bot.send_message(target_user_id, f"{header}\n<i>(Видеосообщение / Кружочек)</i>", parse_mode=ParseMode.HTML)
        await bot.send_video_note(target_user_id, input_file)
    elif content_type == "document":
        input_file = BufferedInputFile(file_bytes, filename="file.bin")
        await bot.send_document(target_user_id, input_file, caption=caption, parse_mode=ParseMode.HTML)
    elif content_type == "audio":
        input_file = BufferedInputFile(file_bytes, filename="audio.mp3")
        await bot.send_audio(target_user_id, input_file, caption=caption, parse_mode=ParseMode.HTML)
    elif content_type == "animation":
        input_file = BufferedInputFile(file_bytes, filename="anim.gif")
        await bot.send_animation(target_user_id, input_file, caption=caption, parse_mode=ParseMode.HTML)


async def send_saved_content(target_user_id: int, header: str, content_type: str, text: str, file_id: str | None):
    """Отправка обычных кэшированных сообщений при удалении."""
    safe_text = html.escape(text) if text else ""
    caption = f"{header}\n\n💬 <b>Подпись:</b>\n<blockquote>{safe_text}</blockquote>" if safe_text else header

    if content_type == "text" or not file_id:
        full_text = f"{header}\n\n💬 <b>Текст:</b>\n<blockquote>{safe_text or '[Пустое сообщение]'}</blockquote>"
        await bot.send_message(target_user_id, full_text, parse_mode=ParseMode.HTML)
        return

    try:
        # Сначала пробуем быструю отправку по file_id
        if content_type == "photo":
            await bot.send_photo(target_user_id, file_id, caption=caption, parse_mode=ParseMode.HTML)
        elif content_type == "video":
            await bot.send_video(target_user_id, file_id, caption=caption, parse_mode=ParseMode.HTML)
        elif content_type == "voice":
            await bot.send_voice(target_user_id, file_id, caption=caption, parse_mode=ParseMode.HTML)
        elif content_type == "document":
            await bot.send_document(target_user_id, file_id, caption=caption, parse_mode=ParseMode.HTML)
        elif content_type == "audio":
            await bot.send_audio(target_user_id, file_id, caption=caption, parse_mode=ParseMode.HTML)
        elif content_type == "animation":
            await bot.send_animation(target_user_id, file_id, caption=caption, parse_mode=ParseMode.HTML)
        elif content_type == "video_note":
            await bot.send_message(target_user_id, f"{header}\n<i>(Видеосообщение / Кружочек)</i>", parse_mode=ParseMode.HTML)
            await bot.send_video_note(target_user_id, file_id)
        elif content_type == "sticker":
            await bot.send_message(target_user_id, f"{header}\n<i>(Стикер)</i>", parse_mode=ParseMode.HTML)
            await bot.send_sticker(target_user_id, file_id)
    except Exception:
        # Если прямая пересылка запрещена, скачиваем и перезаливаем файл
        await download_and_send_media(target_user_id, header, content_type, text, file_id)


@dp.message(CommandStart())
async def cmd_start(message: Message):
    log(f"👋 Пользователь {message.from_user.full_name} нажал /start")
    welcome_text = (
        f"👋 <b>Привет, {html.escape(message.from_user.first_name)}!</b>\n\n"
        f"Я бот для перехвата <b>удаленных</b>, <b>измененных</b> и <b>сгорающих</b> сообщений.\n\n"
        f"⚙️ <b>Как подключить:</b>\n"
        f"1. Откройте <b>Настройки ➔ Telegram для бизнеса ➔ Чат-боты</b>.\n"
        f"2. Добавьте этого бота.\n\n"
        f"🔥 <b>Как сохранить сгорающее фото/видео:</b>\n"
        f"Просто <b>ответьте (Reply)</b> любым текстом на сгорающее сообщение в чате, и я сразу пришлю его вам сюда!"
    )
    await message.answer(welcome_text, parse_mode=ParseMode.HTML)


@dp.business_connection()
async def handle_business_connect(connection: BusinessConnection):
    owner_id = connection.user.id
    owner_name = connection.user.full_name
    if connection.is_enabled:
        cursor.execute(
            "INSERT OR REPLACE INTO connections (connection_id, owner_id, owner_name) VALUES (?, ?, ?)",
            (connection.id, owner_id, owner_name)
        )
        conn.commit()
        log(f"✅ Пользователь {owner_name} (ID: {owner_id}) подключил бота.")
        try:
            await bot.send_message(
                owner_id,
                "✅ <b>Бот успешно подключен!</b>\nОтветьте на любое сгорающее фото/видео в чате, чтобы сохранить его.",
                parse_mode=ParseMode.HTML
            )
        except Exception:
            pass


# 1. Перехват сообщений и СОХРАНЕНИЕ СГОРАЮЩИХ МЕДИА ПО ОТВЕТУ
@dp.business_message()
async def handle_business_message(message: Message):
    conn_id = message.business_connection_id
    owner_id = await get_owner_id(conn_id)
    if not owner_id:
        return

    # А) Когда ВЫ отвечаете (Reply) на сообщение собеседника
    if message.from_user and message.from_user.id == owner_id:
        if message.reply_to_message:
            replied = message.reply_to_message
            if replied.from_user and replied.from_user.id == owner_id:
                return

            sender_info = format_sender(
                replied.from_user.full_name if replied.from_user else "Неизвестный",
                replied.from_user.username if replied.from_user else None
            )
            content_type, text, file_id = extract_content(replied)

            if file_id:
                is_secret = getattr(replied, "has_protected_content", False)
                title = "🔥 <b>Сохранено секретное (сгорающее) медиа!</b>" if is_secret else "📌 <b>Сохранено медиа по вашему ответу!</b>"
                header = f"{title}\n👤 <b>От:</b> {sender_info}"

                log(f"🔥 [Владелец ID:{owner_id}] Скачиваю медиа из реплая (тип: {content_type}, секретное: {is_secret})...")
                try:
                    # Скачиваем файл в память и загружаем как новый (обходит защиту сгорающих фото!)
                    await download_and_send_media(owner_id, header, content_type, text, file_id)
                    log(f"✅ Медиа успешно скачано и отправлено пользователю ID:{owner_id}!")
                except Exception as e:
                    log(f"⚠️ Ошибка скачивания медиа: {e}")
                    await bot.send_message(
                        owner_id,
                        f"{header}\n⚠️ <i>Не удалось скачать медиафайл: {e}</i>",
                        parse_mode=ParseMode.HTML
                    )
        return

    # Б) Когда пишет собеседник — сохраняем в базу на случай удаления
    sender_id = message.from_user.id if message.from_user else 0
    sender_name = message.from_user.full_name if message.from_user else "Неизвестный"
    sender_username = message.from_user.username if message.from_user else None
    content_type, text, file_id = extract_content(message)

    log(f"📥 [Владелец ID:{owner_id}] Кэш от {sender_name} | Тип: {content_type}")

    cursor.execute(
        """INSERT OR REPLACE INTO messages 
           (connection_id, chat_id, message_id, sender_id, sender_name, sender_username, content_type, text, file_id) 
           VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
        (conn_id, message.chat.id, message.message_id, sender_id, sender_name, sender_username, content_type, text, file_id)
    )
    conn.commit()


# 2. Отслеживание редактирования
@dp.edited_business_message()
async def handle_edited_message(message: Message):
    conn_id = message.business_connection_id
    owner_id = await get_owner_id(conn_id)
    if not owner_id or (message.from_user and message.from_user.id == owner_id):
        return

    cursor.execute(
        "SELECT text FROM messages WHERE connection_id = ? AND chat_id = ? AND message_id = ?",
        (conn_id, message.chat.id, message.message_id)
    )
    row = cursor.fetchone()
    old_text = row[0] if row else "[Оригинал не был сохранен]"
    new_text = message.text or message.caption or ""

    if old_text == new_text:
        return

    cursor.execute(
        "UPDATE messages SET text = ? WHERE connection_id = ? AND chat_id = ? AND message_id = ?",
        (new_text, conn_id, message.chat.id, message.message_id)
    )
    conn.commit()

    sender_name = message.from_user.full_name if message.from_user else "Неизвестный"
    sender_info = format_sender(sender_name, message.from_user.username if message.from_user else None)

    log(f"✏️ [Владелец ID:{owner_id}] {sender_name} изменил сообщение")

    alert = (
        f"✏️ <b>Сообщение отредактировано</b>\n"
        f"👤 <b>От:</b> {sender_info}\n\n"
        f"<b>Было:</b>\n<blockquote>{html.escape(old_text or '[Пусто]')}</blockquote>\n"
        f"<b>Стало:</b>\n<blockquote>{html.escape(new_text or '[Пусто]')}</blockquote>"
    )
    await bot.send_message(owner_id, alert, parse_mode=ParseMode.HTML)


# 3. Отслеживание удаления
@dp.deleted_business_messages()
async def handle_deleted_messages(event: BusinessMessagesDeleted):
    conn_id = event.business_connection_id
    owner_id = await get_owner_id(conn_id)
    if not owner_id:
        return

    for msg_id in event.message_ids:
        cursor.execute(
            """SELECT sender_name, sender_username, content_type, text, file_id 
               FROM messages WHERE connection_id = ? AND chat_id = ? AND message_id = ?""",
            (conn_id, event.chat.id, msg_id)
        )
        row = cursor.fetchone()

        if not row:
            continue

        sender_name, sender_username, content_type, text, file_id = row
        sender_info = format_sender(sender_name, sender_username)
        header = f"🗑 <b>Удалено сообщение!</b>\n👤 <b>Чат:</b> {sender_info}"

        log(f"🗑 [Владелец ID:{owner_id}] ПЕРЕХВАЧЕНО УДАЛЕНИЕ от {sender_name} | Тип: {content_type}")

        try:
            await send_saved_content(owner_id, header, content_type, text, file_id)
        except Exception as e:
            log(f"⚠️ Ошибка отправки: {e}")

        cursor.execute(
            "DELETE FROM messages WHERE connection_id = ? AND chat_id = ? AND message_id = ?",
            (conn_id, event.chat.id, msg_id)
        )
        conn.commit()


async def main():
    log("🚀 Безопасный Бизнес-бот (aiogram) запущен! Ожидание событий...")
    await dp.start_polling(bot)

if __name__ == "__main__":
    asyncio.run(main())
