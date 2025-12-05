from typing import List, Tuple
from telegram import Update, InlineKeyboardMarkup, InlineKeyboardButton
from telegram.ext import ContextTypes, CommandHandler, CallbackQueryHandler, MessageHandler, filters

from ..models import User, Notification
from ..loaders import get_course_by_id, get_group_link


def _is_admin(context: ContextTypes.DEFAULT_TYPE, user_id: int) -> bool:
    return user_id == context.bot_data.get("ADMIN_ID")


async def _send_pending_list(update: Update, context: ContextTypes.DEFAULT_TYPE):
    users: List[User] = await User.find_all().to_list()
    buttons = []
    for u in users:
        for e in u.courses:
            if e.approval_status == "pending":
                course = get_course_by_id(e.course_id) or {"name": e.course_id}
                student_name = u.full_name or str(u.telegram_id)
                buttons.append([
                    InlineKeyboardButton(
                        f"{student_name} • {course.get('name')}",
                        callback_data=f"admin_pending_{u.telegram_id}_{e.course_id}",
                    )
                ])
    if not buttons:
        msg = "لا توجد طلبات قيد الانتظار."
        if update.message:
            await update.message.reply_text(msg)
        else:
            await update.effective_chat.send_message(msg)
        return
    text = "✅ **الطلبات المعلقة للموافقة على الدفع**\n\nاختر طلبًا لعرض التفاصيل:"
    if update.message:
        await update.message.reply_text(text, reply_markup=InlineKeyboardMarkup(buttons))
    else:
        await update.effective_chat.send_message(text, reply_markup=InlineKeyboardMarkup(buttons))


async def admin_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not _is_admin(context, update.effective_user.id):
        await update.message.reply_text("❌ غير مخول.")
        return
    await _send_pending_list(update, context)


async def handle_admin_menu_text(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle admin menu button clicks"""
    if not update.message or not update.message.text:
        return
    
    text = update.message.text.strip()
    admin_id = context.bot_data.get("ADMIN_ID")
    
    # Only admin can use these buttons
    if update.effective_user.id != admin_id:
        return
    
    if text == "✅ الموافقة على الدفع":
        await admin_cmd(update, context)
    elif text == "👥 قائمة الطلاب":
        await students_cmd(update, context)
    elif text == "📢 بث جماعي":
        await broadcast_cmd(update, context)
    elif text in ("📢 ارسال رسالة", "📢  ارسال رسالة"):
        # زر "ارسال رسالة" يفتح الآن قائمة الطلاب لإرسال رسالة لطالب محدد
        await students_cmd(update, context)
    elif text == "📊 الإحصائيات":
        await stats_cmd(update, context)
    elif text == "🏠 الرئيسية":
        from .registration import start
        await start(update, context)


async def admin_pending_detail_cb(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    await q.answer()
    if not _is_admin(context, q.from_user.id):
        await q.edit_message_text("❌ غير مخول.")
        return
    try:
        _, _, sid, course_id = q.data.split("_", 3)
        sid = int(sid)
    except Exception:
        await q.edit_message_text("❌ بيانات الطلب غير صالحة.")
        return
    user: User = await User.find_one(User.telegram_id == sid)
    course = get_course_by_id(course_id) or {"name": course_id}
    student_name = (user.full_name if user else None) or str(sid)
    text = (
        "طلب قيد المراجعة:\n"
        f"الطالب: {student_name}\n"
        f"المعرف: {sid}\n"
        f"الدورة/المادة: {course.get('name')}\n"
    )
    receipt = None
    if user:
        for e in user.courses:
            if e.course_id == course_id:
                receipt = e.payment_receipt
                break
    kb = InlineKeyboardMarkup([
        [
            InlineKeyboardButton("موافقة", callback_data=f"admin_approve_{sid}_{course_id}"),
            InlineKeyboardButton("رفض", callback_data=f"admin_reject_{sid}_{course_id}"),
        ]
    ])
    if receipt:
        try:
            await context.bot.send_photo(
                chat_id=update.effective_chat.id,
                photo=receipt,
                caption=text,
                reply_markup=kb,
            )
            await q.edit_message_reply_markup(reply_markup=None)
            return
        except Exception:
            pass
    await q.edit_message_text(text, reply_markup=kb)


# ========== Student -> Admin contact ==========
async def contact_admin_cb(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    await q.answer()
    context.user_data["awaiting_contact_message"] = True
    await q.edit_message_text(
        "💬 **تواصل مع الإدارة**\n\n"
        "أرسل رسالتك الآن وسيتم إيصالها للإدارة.\n"
        "أرسل /cancel للإلغاء."
    )


async def capture_messages(update: Update, context: ContextTypes.DEFAULT_TYPE):
    # Student contacting admin
    if context.user_data.get("awaiting_contact_message") and update.message and update.message.text:
        admin_id = context.bot_data.get("ADMIN_ID")
        student_name = update.effective_user.full_name or f"الطالب {update.effective_user.id}"
        try:
            await context.bot.send_message(
                chat_id=admin_id,
                text=f"📧 **رسالة من الطالب**\n\n"
                     f"👤 الاسم: {student_name}\n"
                     f"🆔 المعرف: {update.effective_user.id}\n\n"
                     f"💬 الرسالة:\n{update.message.text}",
            )
        except Exception as e:
            await update.message.reply_text(f"❌ حدث خطأ: {str(e)}")
            return
        context.user_data.pop("awaiting_contact_message", None)
        await update.message.reply_text("✅ تم إرسال رسالتك للمعلمة شهد طراف بنجاح!")
        return

    # Admin broadcast flow
    if _is_admin(context, update.effective_user.id) and context.user_data.get("awaiting_broadcast") and update.message and update.message.text:
        from ..models import User
        text = update.message.text
        try:
            users = await User.find_all().to_list()
            success_count = 0
            for u in users:
                try:
                    await context.bot.send_message(
                        chat_id=u.telegram_id, 
                        text=f"📢 **رسالة من المعلمة**\n\n{text}"
                    )
                    success_count += 1
                except Exception:
                    continue
        except Exception as e:
            await update.message.reply_text(f"❌ حدث خطأ: {str(e)}")
            return
        context.user_data.pop("awaiting_broadcast", None)
        await update.message.reply_text(f"✅ تم إرسال البث لـ {success_count} طالب.")
        return

    # Admin direct message flow
    if _is_admin(context, update.effective_user.id) and context.user_data.get("awaiting_direct_to") and update.message and update.message.text:
        tid = context.user_data.get("awaiting_direct_to")
        try:
            await context.bot.send_message(
                chat_id=tid, 
                text=f"📧 **رسالة من المعلمة**\n\n{update.message.text}"
            )
        except Exception as e:
            await update.message.reply_text(f"❌ حدث خطأ: {str(e)}")
            return
        context.user_data.pop("awaiting_direct_to", None)
        await update.message.reply_text("✅ تم إرسال الرسالة للطالب.")
        return


async def approve_cb(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    await q.answer()
    if not _is_admin(context, q.from_user.id):
        await q.edit_message_text("غير مخول.")
        return
    _, _, sid, course_id = q.data.split("_", 3)
    sid = int(sid)

    user: User = await User.find_one(User.telegram_id == sid)
    if not user:
        await q.edit_message_text("الطالب غير موجود.")
        return
    updated = False
    for e in user.courses:
        if e.course_id == course_id:
            e.approval_status = "approved"
            updated = True
            break
    if not updated:
        await q.edit_message_text("لا يوجد طلب لهذه الدورة.")
        return

    user.notifications.append(
        Notification(
            student_id=user.telegram_id,
            type="approved",
            message=f"تمت الموافقة على تسجيلك في {course_id}",
        )
    )
    await user.save()

    course = get_course_by_id(course_id) or {"name": course_id}
    course_name = course.get("name")
    group_link = get_group_link(course_id)

    # Notify student immediately
    try:
        text = f"تمت الموافقة على تسجيلك في {course_name} ✅"
        if group_link:
            text += f"\n\nرابط المجموعة: {group_link}"
        await context.bot.send_message(chat_id=sid, text=text)
    except Exception:
        pass

    # Notify admin that approval was completed
    admin_id = context.bot_data.get("ADMIN_ID")
    if admin_id:
        student_name = user.full_name or str(sid)
        try:
            await context.bot.send_message(
                chat_id=admin_id,
                text=(
                    "✅ تم تنفيذ الموافقة بنجاح\n\n"
                    f"👤 الطالب: {student_name} ({sid})\n"
                    f"📘 الدورة/المادة: {course_name}"
                ),
            )
        except Exception:
            pass

    await q.edit_message_text("تمت الموافقة وإرسال الرسالة للطالب.")


async def reject_cb(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    await q.answer()
    if not _is_admin(context, q.from_user.id):
        await q.edit_message_text("غير مخول.")
        return
    _, _, sid, course_id = q.data.split("_", 3)
    sid = int(sid)

    user: User = await User.find_one(User.telegram_id == sid)
    if not user:
        await q.edit_message_text("الطالب غير موجود.")
        return
    updated = False
    for e in user.courses:
        if e.course_id == course_id:
            e.approval_status = "rejected"
            updated = True
            break
    if not updated:
        await q.edit_message_text("لا يوجد طلب لهذه الدورة.")
        return

    user.notifications.append(
        Notification(
            student_id=user.telegram_id,
            type="rejected",
            message=f"تم رفض طلبك للدورة {course_id}",
        )
    )
    await user.save()

    course = get_course_by_id(course_id) or {"name": course_id}
    try:
        await context.bot.send_message(
            chat_id=sid,
            text=f"تم رفض طلبك للدورة {course.get('name')} ❌",
        )
    except Exception:
        pass

    await q.edit_message_text("تم الرفض.")


async def ack_notification_cb(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    await q.answer("تم")
    await q.edit_message_reply_markup(reply_markup=None)


async def start_chat_cb(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    await q.answer()
    await q.edit_message_text("سيتم التواصل مع الأدمن.")


async def cancel_chat_cb(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    await q.answer()
    await q.edit_message_text("تم إلغاء طلب المراسلة.")


# ========== Admin utilities ==========
async def cancel_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data.pop("awaiting_contact_message", None)
    context.user_data.pop("awaiting_broadcast", None)
    context.user_data.pop("awaiting_direct_to", None)
    await update.message.reply_text("تم الإلغاء.")


async def broadcast_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not _is_admin(context, update.effective_user.id):
        await update.message.reply_text("❌ غير مخول.")
        return
    context.user_data["awaiting_broadcast"] = True
    await update.message.reply_text(
        "📢 **بث جماعي**\n\n"
        "أرسل نص البث الآن لإرساله إلى جميع الطلاب المسجلين."
    )


async def students_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not _is_admin(context, update.effective_user.id):
        await update.message.reply_text("❌ غير مخول.")
        return
    users: List[User] = await User.find_all().to_list()
    buttons = []
    for u in users[:100]:
        name = u.full_name or str(u.telegram_id)
        buttons.append([InlineKeyboardButton(f"👤 {name}", callback_data=f"admin_msg_{u.telegram_id}")])
    if not buttons:
        await update.message.reply_text("❌ لا يوجد طلاب.")
        return
    await update.message.reply_text(
        f"👥 **قائمة الطلاب ({len(users)})**\n\n"
        "اختر الطالب لإرسال رسالة له:", 
        reply_markup=InlineKeyboardMarkup(buttons)
    )


async def admin_msg_select_cb(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    await q.answer()
    if not _is_admin(context, q.from_user.id):
        await q.edit_message_text("❌ غير مخول.")
        return
    _, _, tid = q.data.partition("admin_msg_")
    try:
        tid = int(tid)
    except Exception:
        await q.edit_message_text("❌ معرف غير صالح.")
        return
    context.user_data["awaiting_direct_to"] = tid
    # Get student name
    student = await User.find_one(User.telegram_id == tid)
    student_name = student.full_name if student else f"الطالب {tid}"
    await q.edit_message_text(
        f"📧 **إرسال رسالة**\n\n"
        f"👤 إلى: {student_name}\n\n"
        f"أرسل رسالتك الآن.\n"
        f"أرسل /cancel للإلغاء."
    )


async def stats_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not _is_admin(context, update.effective_user.id):
        await update.message.reply_text("❌ غير مخول.")
        return
    users: List[User] = await User.find_all().to_list()
    buttons = []
    for u in users[:100]:
        name = u.full_name or f"الطالب {u.telegram_id}"
        buttons.append([InlineKeyboardButton(f"👤 {name}", callback_data=f"admin_stat_{u.telegram_id}")])
    if not buttons:
        await update.message.reply_text("❌ لا يوجد طلاب.")
        return
    await update.message.reply_text(
        f"📊 **إحصائيات المعلم**\n\n"
        f"👥 **عدد المستخدمين:** {len(users)}\n\n"
        f"اختر طالبًا لعرض تفاصيله:",
        reply_markup=InlineKeyboardMarkup(buttons)
    )


async def admin_stat_select_cb(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    await q.answer()
    if not _is_admin(context, q.from_user.id):
        await q.edit_message_text("❌ غير مخول.")
        return
    _, _, tid = q.data.partition("admin_stat_")
    try:
        tid = int(tid)
    except Exception:
        await q.edit_message_text("❌ معرف غير صالح.")
        return
    user: User = await User.find_one(User.telegram_id == tid)
    if not user:
        await q.edit_message_text("❌ الطالب غير موجود.")
        return
    name = user.full_name or f"الطالب {tid}"
    courses = user.courses or []
    course_lines = []
    for e in courses:
        c = get_course_by_id(e.course_id) or {"name": e.course_id}
        course_lines.append(f"• {c.get('name')}")
    courses_block = "\n".join(course_lines) if course_lines else "لا يوجد مواد مسجلة."
    year_text = user.study_year if getattr(user, "study_year", None) else "-"
    spec_text = user.specialization if getattr(user, "specialization", None) else "-"
    text = (
        f"👤 الاسم: {name}\n"
        f"🆔 المعرف: {tid}\n"
        f"📞 الرقم: {user.phone or '-'}\n"
        f"✉️ البريد: {user.email or '-'}\n"
        f"📚 السنة الدراسية: {year_text}\n"
        f"🎓 التخصص: {spec_text}\n"
        f"📚 عدد المواد المسجلة: {len(courses)}\n\n"
        f"📋 الأسماء:\n{courses_block}"
    )
    await q.edit_message_text(text)


async def _flush_approval_batch(context: ContextTypes.DEFAULT_TYPE):
    try:
        job = getattr(context, "job", None)
        sid = job.data.get("sid") if job and job.data else None
    except Exception:
        return
    batches = context.bot_data.get("approval_batch") or {}
    entry = batches.pop(sid, None)
    if not entry or not entry.get("items"):
        return
    items = entry["items"]
    if len(items) == 1:
        c = items[0]
        text = f"تمت الموافقة على تسجيلك في {c.get('course_name')} ✅"
        if c.get("group_link"):
            text += f"\n\nرابط المجموعة: {c.get('group_link')}"
        kb = InlineKeyboardMarkup([[InlineKeyboardButton("تم", callback_data=f"notification_course_approved_{c.get('course_id')}")]])
    else:
        text = "تمت الموافقة على تسجيلك في الدورات التالية: ✅\n\n"
        for c in items:
            text += f"• {c.get('course_name')}\n"
        has_links = any(c.get("group_link") for c in items)
        if has_links:
            text += "\nروابط المجموعات:\n"
            for c in items:
                if c.get("group_link"):
                    text += f"• {c.get('course_name')}: {c.get('group_link')}\n"
        kb = InlineKeyboardMarkup([[InlineKeyboardButton("تم", callback_data="notification_course_approved_batch")]])

    try:
        await context.bot.send_message(chat_id=sid, text=text, reply_markup=kb)
        admin_id = context.bot_data.get("ADMIN_ID")
        student = None
        try:
            student = await User.find_one(User.telegram_id == sid)
        except Exception:
            student = None
        student_name = (student.full_name if student else None) or str(sid)
        if admin_id:
            if len(items) == 1:
                await context.bot.send_message(
                    chat_id=admin_id,
                    text=(
                        "✅ تم تنفيذ الموافقة بنجاح\n\n"
                        f"👤 الطالب: {student_name} ({sid})\n"
                        f"📘 الدورة/المادة: {items[0].get('course_name')}"
                    ),
                )
            else:
                courses_block = "\n".join([f"• {c.get('course_name')}" for c in items])
                await context.bot.send_message(
                    chat_id=admin_id,
                    text=(
                        "✅ تم تنفيذ الموافقات بنجاح\n\n"
                        f"👤 الطالب: {student_name} ({sid})\n"
                        f"📚 المواد:\n{courses_block}"
                    ),
                )
    except Exception:
        pass


def get_handlers():
    return [
        CommandHandler("admin", admin_cmd),
        CommandHandler("cancel", cancel_cmd),
        CommandHandler("broadcast", broadcast_cmd),
        CommandHandler("students", students_cmd),
        CommandHandler("stats", stats_cmd),
        CallbackQueryHandler(admin_pending_detail_cb, pattern="^admin_pending_"),
        CallbackQueryHandler(approve_cb, pattern="^admin_approve_"),
        CallbackQueryHandler(reject_cb, pattern="^admin_reject_"),
        CallbackQueryHandler(ack_notification_cb, pattern="^notification_course_approved_"),
        CallbackQueryHandler(admin_msg_select_cb, pattern="^admin_msg_"),
        CallbackQueryHandler(admin_stat_select_cb, pattern="^admin_stat_"),
        CallbackQueryHandler(start_chat_cb, pattern="^start_chat$"),
        CallbackQueryHandler(cancel_chat_cb, pattern="^cancel_chat$"),
        # Admin menu buttons - must be before other text handlers
        MessageHandler(
            filters.TEXT
            & filters.Regex(
                "^(✅ الموافقة على الدفع|👥 قائمة الطلاب|📢 بث جماعي|📢 ارسال رسالة|📢  ارسال رسالة|📊 الإحصائيات|🏠 الرئيسية)$"
            ),
            handle_admin_menu_text,
        ),
    ]


def get_catchall_handler():
    return MessageHandler(filters.TEXT & ~filters.COMMAND, capture_messages)
