from telegram import Update, ReplyKeyboardMarkup
from telegram.ext import ContextTypes, ConversationHandler, CommandHandler, MessageHandler, filters
from beanie import PydanticObjectId
from datetime import datetime
from ..models import User
from ..keyboards import categories_keyboard, main_menu_keyboard, admin_menu_keyboard

ASKING_NAME, ASKING_PHONE, ASKING_EMAIL, ASKING_YEAR, ASKING_SPECIALIZATION = range(5)


async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    admin_id = context.bot_data.get("ADMIN_ID")
    if admin_id and user.id == admin_id:
        await update.message.reply_text(
            "🔑 **مرحباً أستاذة شهد!**\n\n"
            "🎯 **لوحة التحكم الإدارية**\n"
            "اختر من القائمة أدناه لإدارة الدورات والطلاب:",
            reply_markup=admin_menu_keyboard(),
        )
        return ConversationHandler.END
    existing = await User.find_one(User.telegram_id == user.id)
    if existing and existing.phone and existing.email:
        existing.last_active = datetime.utcnow()
        await existing.save()
        await update.message.reply_text(
            f"👋 **مرحباً {existing.full_name}!**\n\n"
            "🎓 **منصة التعليم الإلكترونية**\n\n"
            "اختر من القائمة أدناه:", 
            reply_markup=main_menu_keyboard()
        )
        return ConversationHandler.END
    await update.message.reply_text("👤 أهلاً بك! ما هو اسمك الكامل؟")
    return ASKING_NAME


async def ask_phone(update: Update, context: ContextTypes.DEFAULT_TYPE):
    name = (update.message.text or "").strip()
    if name == "❌ إلغاء":
        await update.message.reply_text("تم إلغاء التسجيل.")
        return ConversationHandler.END
    context.user_data["full_name"] = name
    await update.message.reply_text("رقم هاتفك؟\nمثال: +963999999999")
    return ASKING_PHONE


async def ask_email(update: Update, context: ContextTypes.DEFAULT_TYPE):
    phone = (update.message.text or "").strip()
    if phone == "❌ إلغاء":
        await update.message.reply_text("تم إلغاء التسجيل.")
        return ConversationHandler.END
    # basic phone validation
    if not phone.startswith("+") or len(phone) < 10:
        await update.message.reply_text("❌ يرجى إدخال رقم هاتف صحيح\nمثال: +963999999999")
        return ASKING_PHONE
    context.user_data["phone"] = phone
    await update.message.reply_text("بريدك الإلكتروني؟\nمثال: student@example.com")
    return ASKING_EMAIL


async def ask_study_year(update: Update, context: ContextTypes.DEFAULT_TYPE):
    email = (update.message.text or "").strip().lower()
    if email == "❌ إلغاء":
        await update.message.reply_text("❌ تم إلغاء التسجيل.")
        return ConversationHandler.END
    # basic email validation
    if "@" not in email or "." not in email:
        await update.message.reply_text("❌ يرجى إدخال بريد إلكتروني صحيح\nمثال: student@example.com")
        return ASKING_EMAIL
    context.user_data["email"] = email
    await update.message.reply_text(
        "📚 في أي سنة دراسية أنت؟\n"
        "اكتب 3 أو 4 أو 5."
    )
    return ASKING_YEAR


async def ask_specialization(update: Update, context: ContextTypes.DEFAULT_TYPE):
    year_text = (update.message.text or "").strip()
    if year_text == "❌ إلغاء":
        await update.message.reply_text("تم إلغاء التسجيل.")
        return ConversationHandler.END
    try:
        year = int(year_text)
    except ValueError:
        await update.message.reply_text("❌ يرجى إدخال سنة دراسية صحيحة: 3 أو 4 أو 5.")
        return ASKING_YEAR
    if year not in (3, 4, 5):
        await update.message.reply_text("❌ السنوات المتاحة حالياً هي: 3 أو 4 أو 5.\nيرجى المحاولة مرة أخرى.")
        return ASKING_YEAR
    context.user_data["study_year"] = year
    await update.message.reply_text(
        "ما هو تخصصك؟\n"
        "اكتب أحد الخيارات التالية:\n"
        "برمجيات\n"
        "ذكاء\n"
        "شبكات"
    )
    return ASKING_SPECIALIZATION


async def finish_registration(update: Update, context: ContextTypes.DEFAULT_TYPE):
    spec_text = (update.message.text or "").strip()
    if spec_text == "❌ إلغاء":
        await update.message.reply_text("❌ تم إلغاء التسجيل.")
        return ConversationHandler.END

    normalized = spec_text.replace(" ", "").lower()
    spec_map = {
        "برمجيات": "برمجيات",
        "software": "برمجيات",
        "ذكاء": "ذكاء",
        "ذكاءاصطناعي": "ذكاء",
        "ai": "ذكاء",
        "شبكات": "شبكات",
        "network": "شبكات",
        "networks": "شبكات",
    }
    specialization = spec_map.get(normalized)
    if not specialization:
        await update.message.reply_text(
            "❌ يرجى اختيار تخصص صحيح من القائمة:\n"
            "برمجيات، ذكاء، شبكات."
        )
        return ASKING_SPECIALIZATION

    full_name = context.user_data.get("full_name")
    phone = context.user_data.get("phone")
    email = context.user_data.get("email")
    study_year = context.user_data.get("study_year")
    tg_user = update.effective_user
    user_doc = await User.find_one(User.telegram_id == tg_user.id)
    is_new = user_doc is None
    if not user_doc:
        user_doc = User(
            telegram_id=tg_user.id,
            full_name=full_name,
            phone=phone,
            email=email,
            study_year=study_year,
            specialization=specialization,
        )
    else:
        user_doc.full_name = full_name
        user_doc.phone = phone
        user_doc.email = email
        user_doc.study_year = study_year
        user_doc.specialization = specialization
        user_doc.last_active = datetime.utcnow()
    await user_doc.save()

    admin_id = context.bot_data.get("ADMIN_ID")
    if is_new and admin_id:
        try:
            await context.bot.send_message(
                chat_id=admin_id,
                text=(
                    "👤 تم تسجيل طالب جديد\n\n"
                    f"الاسم: {full_name}\n"
                    f"🆔 المعرف: {tg_user.id}\n"
                    f"📞 الهاتف: {phone}\n"
                    f"✉️ البريد: {email}\n"
                    f"📚 السنة الدراسية: {study_year or '-'}\n"
                    f"🎓 التخصص: {specialization or '-'}"
                ),
            )
        except Exception:
            pass

    await update.message.reply_text(
        "✅ **تم التسجيل بنجاح!**\n\n"
        f"👋 أهلاً بك {full_name}!\n\n"
        "🎓 **منصة التعليم الإلكترونية**\n"
        "اختر من القائمة أدناه لبدء رحلتك التعليمية:", 
        reply_markup=main_menu_keyboard()
    )
    return ConversationHandler.END


async def cancel(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("تم الإلغاء.")
    return ConversationHandler.END


def get_handler() -> ConversationHandler:
    return ConversationHandler(
        entry_points=[CommandHandler("start", start)],
        states={
            ASKING_NAME: [MessageHandler(filters.TEXT & ~filters.COMMAND, ask_phone)],
            ASKING_PHONE: [MessageHandler(filters.TEXT & ~filters.COMMAND, ask_email)],
            ASKING_EMAIL: [MessageHandler(filters.TEXT & ~filters.COMMAND, ask_study_year)],
            ASKING_YEAR: [MessageHandler(filters.TEXT & ~filters.COMMAND, ask_specialization)],
            ASKING_SPECIALIZATION: [MessageHandler(filters.TEXT & ~filters.COMMAND, finish_registration)],
        },
        fallbacks=[CommandHandler("cancel", cancel)],
        name="registration_conversation",
        persistent=False,
    )
