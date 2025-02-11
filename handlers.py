import re
import logging
import json
from aiogram import types
from aiogram.dispatcher import Dispatcher
from models import HouseListing
from config import ADMIN_IDS, SOURCE_GROUPS
import state
from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton
import asyncio

# E'lon ID larini aniqlash uchun regex
id_regex = re.compile(r"(?i)\bID[\s:_-]*0*(\d+)\b")

media_group_cache = {}

def get_listing_by_id(post_id: str) -> HouseListing:
    candidates = HouseListing.select().where(HouseListing.post_id == str(post_id))
    if candidates.exists():
        return candidates.get()
    raise HouseListing.DoesNotExist

async def process_media_group(group_id: str, chat_id: int):
    # Wait a short time to allow all parts of the group to arrive.
    await asyncio.sleep(2)
    messages = media_group_cache.pop(group_id, [])
    if not messages:
        return

    # Combine texts from all messages (if a caption or text exists).
    combined_text = " ".join(m.caption or m.text or "" for m in messages)
    match = id_regex.search(combined_text)
    if not match:
        logging.error(f"⚠️ Media guruh {group_id} ichida haqiqiy e'lon ID topilmadi. Saqlanmadi.")
        return

    extracted_id = str(int(match.group(1)))
    try:
        post_url = messages[0].url
    except Exception:
        post_url = ""

    # Build media_data from each message (support photo, video, and document)
    media_data = []
    for msg in messages:
        media_item = None
        if msg.photo:
            media_item = {"type": "photo", "file_id": msg.photo[-1].file_id}
        elif msg.video:
            media_item = {"type": "video", "file_id": msg.video.file_id}
        elif msg.document:
            media_item = {"type": "document", "file_id": msg.document.file_id}
        if media_item:
            media_data.append(media_item)

    # Use the caption from the first message if available; otherwise use the combined text.
    caption = messages[0].caption if messages[0].caption else combined_text

    listing = HouseListing.create(
        post_id=extracted_id,
        post_url=post_url,
        source_message_id=messages[0].message_id,  # using the first message as the representative
        status="active",
        boost_status="unboosted",
        source_group_id=chat_id,
        media_group_id=group_id,
        media_group_data=json.dumps(media_data),
        caption=caption,
    )
    listing.save()
    logging.info(f"✅ Media guruhidagi yangi e'lon saqlandi: {extracted_id}")

async def handle_new_message(message: types.Message):
    if message.chat.id not in SOURCE_GROUPS:
        return

    # If this message is not part of a media group, process it immediately.
    if not message.media_group_id:
        text = message.text or message.caption or ""
        match = id_regex.search(text)
        if not match:
            logging.error("⚠️ Xabarda haqiqiy e'lon ID topilmadi. Saqlanmadi.")
            return
        extracted_id = str(int(match.group(1)))
        try:
            post_url = message.url
        except Exception:
            post_url = ""
        
        media_data = []
        media_item = None
        if message.photo:
            media_item = {"type": "photo", "file_id": message.photo[-1].file_id}
        elif message.video:
            media_item = {"type": "video", "file_id": message.video.file_id}
        elif message.document:
            media_item = {"type": "document", "file_id": message.document.file_id}
        else:
            # No supported media found.
            return
        media_data.append(media_item)
        
        listing = HouseListing.create(
            post_id=extracted_id,
            post_url=post_url,
            source_message_id=message.message_id,
            status="active",
            boost_status="unboosted",
            source_group_id=message.chat.id,
            media_group_id=None,
            media_group_data=json.dumps(media_data),
            caption=message.caption if message.caption else ""
        )
        listing.save()
        logging.info(f"✅ Yangi e'lon saqlandi: {extracted_id}")
        return

    # ----- Media Group Handling -----
    # If the message belongs to a media group, cache it.
    global media_group_cache
    group_id = message.media_group_id
    if group_id not in media_group_cache:
        media_group_cache[group_id] = []
        # Schedule processing of this media group after a short delay.
        asyncio.create_task(process_media_group(group_id, message.chat.id))
    media_group_cache[group_id].append(message)

async def start_command(message: types.Message):
    if message.from_user.id in ADMIN_IDS:
        total = HouseListing.select().count()
        active = HouseListing.select().where(HouseListing.status == "active").count()
        sent = HouseListing.select().where(HouseListing.status == "sent").count()
        boosted = HouseListing.select().where(HouseListing.boost_status == "boosted").count()
        deleted = HouseListing.select().where(HouseListing.status == "deleted").count()
        error_count = HouseListing.select().where(HouseListing.status == "error").count()

        stats_message = (
            f"📊 <b>Bot Statistika:</b>\n"
            f"📝 Jami e'lonlar: {total}\n"
            f"✅ Faol: {active}\n"
            f"📤 Yuborilgan: {sent}\n"
            f"🚀 Boost qilingan: {boosted}\n"
            f"🗑️ O'chirilgan: {deleted}\n"
            f"❗ Xatoliklar: {error_count}\n\n"
            f"Manba guruhlar: {SOURCE_GROUPS}\n"
            f"Maqsad guruhlari: (config da belgilangan)\n"
        )
        await message.answer(stats_message, parse_mode="HTML")
    else:

        source_groups = [
            "НАВОИЙ ХОВЛИ/КОТТЕДЖЛАР",
            "НАВОИЙ 4 ХОНА 5 ХОНА КИЛИНГАН УЙЛАР",
            "НАВОИЙ 5 ХОНАЛИ УЙЛАР",
            "НАВОИЙ 4 ХОНАЛИ УЙЛАР",
            "НАВОИЙ 3 ХОНАЛИ УЙЛАР",
            "НАВОИЙ ИЖАРА УЙЛАР",
            "НАВОИЙ 1 ХОНАЛИ УЙЛАР",
            "НАВОИЙ 1 ХОНА 2 ХОНА КИЛИНГАН УЙЛАР",
            "НАВОИЙ 2 ХОНА 3 ХОНА КИЛИНГАН УЙЛАР",
            "НАВОИЙ 3 ХОНА 4 ХОНА КИЛИНГАН УЙЛАР",
            "НАВОИЙ УЙЛАР РЕКЛАМАСИ",
            "НАВОИЙ 2 ХОНАЛИ УЙЛАР"
        ]

        group_usernames = ["@navoiy_hovli_kottedj","@navoiy_4_5x_uylar","@navoiy_5x_uylar","@navoiy_4x_uylar","@navoiy_3x_uylar","@navoiy_ijaragaa_uylar","@navoiy_1x_uylar","@navoiy_1_2x_uylar","@navoiy_2_3x_uylar","@navoiy_3_4x_uylar","@navoiy_reklama_uylar","@navoiy_2x_uylar"]

        keyboard = InlineKeyboardMarkup()
        for group_id, group_username in zip(source_groups, group_usernames):
            keyboard.add(InlineKeyboardButton(text=group_id, url=f"https://t.me/{group_username}"))
        welcome_message = "👋 Xush kelibsiz! Iltimos, uy e'lonlarini ko'rish uchun manba guruhni tanlang:"
        await message.answer(welcome_message, reply_markup=keyboard)

async def boost_command(message: types.Message):
    if message.from_user.id not in ADMIN_IDS:
        await message.answer("🚫 Ruxsatsiz buyruq.")
        return
    args = message.get_args().strip()
    if not args:
        await message.answer("ℹ️ Foydalanish: /boost <e'lon_id>")
        return
    try:
        post_id = str(int(args.replace("ID", "").replace("id", "").strip()))
    except ValueError:
        await message.answer("❌ Noto'g'ri e'lon ID formati.")
        return
    try:
        listing = get_listing_by_id(post_id)
        listing.boost_status = "boosted"
        listing.save()
        await message.answer(f"🚀 E'lon {post_id} boost holatiga o'tkazildi!")
    except HouseListing.DoesNotExist:
        await message.answer(f"❌ E'lon {post_id} topilmadi.")

async def unboost_command(message: types.Message):
    if message.from_user.id not in ADMIN_IDS:
        await message.answer("🚫 Ruxsatsiz buyruq.")
        return
    args = message.get_args().strip()
    if not args:
        await message.answer("ℹ️ Foydalanish: /unboost <e'lon_id>")
        return
    try:
        post_id = str(int(args.replace("ID", "").replace("id", "").strip()))
    except ValueError:
        await message.answer("❌ Noto'g'ri e'lon ID formati.")
        return
    try:
        listing = get_listing_by_id(post_id)
        if listing.boost_status != "boosted":
            await message.answer(f"ℹ️ E'lon {post_id} boost qilingan emas.")
            return
        listing.boost_status = "unboosted"
        listing.save()
        await message.answer(f"🔄 E'lon {post_id} boost holatidan chiqarildi.")
    except HouseListing.DoesNotExist:
        await message.answer(f"❌ E'lon {post_id} topilmadi.")

async def delete_command(message: types.Message):
    if message.from_user.id not in ADMIN_IDS:
        await message.answer("🚫 Ruxsatsiz buyruq.")
        return
    args = message.get_args().strip()
    if not args:
        await message.answer("ℹ️ Foydalanish: /del <e'lon_id>")
        return
    try:
        post_id = str(int(args.replace("ID", "").replace("id", "").strip()))
    except ValueError:
        await message.answer("❌ Noto'g'ri e'lon ID formati.")
        return
    try:
        listing = get_listing_by_id(post_id)
        if listing.forwarded_message_ids:
            try:
                fwd_data = json.loads(listing.forwarded_message_ids)
            except Exception as e:
                fwd_data = {}
                logging.error(f"❌ E'lon {post_id} uchun forwarded_message_ids ni tahlil qilishda xato: {e}")
            for chat_id, msg_ids in fwd_data.items():
                for msg_id in msg_ids:
                    try:
                        await message.bot.delete_message(chat_id=int(chat_id), message_id=msg_id)
                    except Exception as e:
                        logging.error(f"❌ Guruh {chat_id} dan {msg_id} xabarni o'chirishda xato: {e}")
        try:
            await message.bot.delete_message(chat_id=listing.source_group_id,
                                             message_id=listing.source_message_id)
        except Exception as e:
            logging.error(f"❌ E'lon {post_id} uchun manba xabarni o'chirishda xato: {e}")
        listing.status = "deleted"
        listing.save()
        await message.answer(f"🗑️ E'lon {post_id} to'liq o'chirildi.")
    except HouseListing.DoesNotExist:
        await message.answer(f"❌ E'lon {post_id} topilmadi.")

async def on_command(message: types.Message):
    if message.from_user.id not in ADMIN_IDS:
        await message.answer("🚫 Ruxsatsiz buyruq.")
        return
    state.SENDING_ENABLED = True
    await message.answer("✅ Yuborish rejimi yoqildi!")

async def off_command(message: types.Message):
    if message.from_user.id not in ADMIN_IDS:
        await message.answer("🚫 Ruxsatsiz buyruq.")
        return
    state.SENDING_ENABLED = False
    await message.answer("⛔ Yuborish rejimi o'chirildi!")

async def refresh_command(message: types.Message):
    if message.from_user.id not in ADMIN_IDS:
        await message.answer("🚫 Ruxsatsiz buyruq.")
        return
    state.REFRESH_REQUESTED = True
    await message.answer("🔄 Bazani yangilash buyruqi qabul qilindi!")

def register_handlers(dp: Dispatcher):
    dp.register_message_handler(handle_new_message, content_types=types.ContentTypes.ANY, chat_id=SOURCE_GROUPS)
    dp.register_message_handler(start_command, commands=["start"])
    dp.register_message_handler(boost_command, commands=["boost"])
    dp.register_message_handler(unboost_command, commands=["unboost"])
    dp.register_message_handler(delete_command, commands=["del"])
    dp.register_message_handler(on_command, commands=["on"])
    dp.register_message_handler(off_command, commands=["off"])
    dp.register_message_handler(refresh_command, commands=["refresh"])
