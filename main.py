chat_id = known_chat_id()
            if chat_id is not None:
                await send_complete_batches(chat_id, application.bot)

            # Also retries errors or missed sends after a service restart.
            # Check quietly once a minute while the group is open.
            await asyncio.sleep(min(60, seconds_until_close()))

        except asyncio.CancelledError:
            raise
        except Exception:
            logger.exception("Welcome scheduler error; retrying in 60 seconds")
            await asyncio.sleep(60)


async def on_post_init(application):
    application.bot_data["welcome_worker"] = asyncio.create_task(
        welcome_reopen_worker(application)
    )
    logger.info("Welcome scheduler started, timezone Asia/Riyadh")


async def on_post_shutdown(application):
    task = application.bot_data.pop("welcome_worker", None)
    if task:
        task.cancel()
        try:
            await task
        except asyncio.CancelledError:
            pass


# --- 6. Telegram member events ---
async def handle_new_members(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.message and update.message.new_chat_members:
        for member in update.message.new_chat_members:
            await process_new_user(member, update.effective_chat.id, context)


async def handle_chat_member_updated(
    update: Update, context: ContextTypes.DEFAULT_TYPE
):
    result = update.chat_member
    if not result:
        return

    old_status = result.old_chat_member.status
    new_status = result.new_chat_member.status

    if (
        old_status in ["left", "kicked", "restricted"]
        and new_status in ["member", "administrator"]
    ):
        await process_new_user(
            result.new_chat_member.user,
            update.effective_chat.id,
            context,
        )


# --- 7. Manual welcome: silent during closing hours ---
async def force_flush_welcome(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat = update.effective_chat
    if not chat or chat.type not in ("group", "supergroup"):
        return
    if not managed_group(chat.id) or is_quiet_hours():
        return  # No replies or welcome messages during quiet hours.

    async with LOCK:
        remember_chat_id(chat.id)
        rows = get_all_db_users()
        if not rows:
            if not is_quiet_hours():
                await update.effective_message.reply_text(
                    "لا يوجد أعضاء بانتظار الترحيب حالياً."
                )
            return

        # Preserve the manual flush command even for fewer than 10 users,
        # but split large backlogs into manageable batches.
        for start in range(0, len(rows), BATCH_SIZE):
            if is_quiet_hours():
                break
            batch = rows[start : start + BATCH_SIZE]
            try:
                await context.bot.send_message(
                    chat_id=chat.id,
                    text=make_welcome_text(batch),
                    parse_mode="HTML",
                )
            except Exception:
                logger.exception("Manual welcome failed; pending names retained")
                break
            clear_db_users([row[0] for row in batch])
            if start + BATCH_SIZE < len(rows):
                await asyncio.sleep(1.2)


# --- 8. Start bot ---
if __name__ == "__main__":
    threading.Thread(target=run_web_server, daemon=True).start()

    init_db()

    if not TOKEN:
        raise ValueError("خطأ: لم يتم العثور على متغير البيئة BOT_TOKEN!")

    app = (
        ApplicationBuilder()
        .token(TOKEN)
        .post_init(on_post_init)
        .post_shutdown(on_post_shutdown)
        .build()
    )

    app.add_handler(CommandHandler("flush", force_flush_welcome))
    app.add_handler(
        MessageHandler(filters.Regex(r"^(رحب|/رحب)$"), force_flush_welcome)
    )
    app.add_handler(
        MessageHandler(
            filters.StatusUpdate.NEW_CHAT_MEMBERS,
            handle_new_members,
        )
    )
    app.add_handler(
        ChatMemberHandler(
