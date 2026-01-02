
async def _process_text_input(update: Update, context: ContextTypes.DEFAULT_TYPE, text: str) -> None:
    """Shared logic for text and transcribed voice."""
    if not text: return
    
    # Check Master Switch
    try:
        user_settings = await get_bot_user_settings()
        if not user_settings.bot.enabled:
             # Allow commands to potentially proceed if they start with / (except if we want total silence/block)
             # Existing logic was: "pass" if command, else reply disabled.
             # But then it fell through to logic. "pass" implies continuing.
             if text.startswith("/"):
                 pass 
             else:
                 await reply_text(update, context, "😴 Bot desactivado desde la App.")
                 return
    except Exception as e:
        logger.error(f"Failed to check bot status: {e}")

    cmd = text.lower().strip()

    if cmd == "ping":
        await reply_text(update, context, "pong")
        return

    # 0. Intercept Pending Inputs (Manual Bolus Edit)
    pending_bolus_req = context.user_data.get("editing_bolus_request")
    if pending_bolus_req:
        try:
            val = float(text.replace(",", "."))
            del context.user_data["editing_bolus_request"]
            
            # Confirm Card
            keyboard = [
                [
                    InlineKeyboardButton(f"✅ Confirmar {val} U", callback_data=f"accept_manual|{val}|{pending_bolus_req}"),
                    InlineKeyboardButton("❌ Cancelar", callback_data=f"cancel|{pending_bolus_req}")
                ]
            ]
            await reply_text(
                update, 
                context, 
                f"¿Confirmas el cambio a **{val} U**?", 
                reply_markup=InlineKeyboardMarkup(keyboard),
                parse_mode="Markdown"
            )
            return
        except ValueError:
            await reply_text(update, context, "⚠️ Por favor, introduce un número válido.")
            return

    # 0. Intercept Pending Inputs (Combo Followup)
    pending_combo_tid = context.user_data.get("pending_combo_tid")
    if pending_combo_tid:
        try:
            units = float(text.replace(",", "."))
            # Clear pending
            del context.user_data["pending_combo_tid"]
            
            # Ask Confirm
            keyboard = [
                [
                    InlineKeyboardButton(f"✅ Registrar {units} U", callback_data=f"combo_confirm|{units}|{pending_combo_tid}"),
                    InlineKeyboardButton("❌ Cancelar", callback_data=f"combo_no|{pending_combo_tid}")
                ]
            ]
            await reply_text(update, context, f"¿Registrar **{units} U** para la 2ª parte del bolo?", reply_markup=InlineKeyboardMarkup(keyboard), parse_mode="Markdown")
            return
        except ValueError:
            await reply_text(update, context, "⚠️ Por favor, introduce un número válido (ej. 2.5).")
            return

    if cmd in ["status", "estado"]:
        res = await tools.execute_tool("get_status_context", {})
        if isinstance(res, tools.ToolError):
            await reply_text(update, context, f"⚠️ {res.message}")
        else:
            await reply_text(
                update,
                context,
                f"📉 BG: {res.bg_mgdl} {res.direction or ''} Δ {res.delta} | IOB {res.iob_u} | COB {res.cob_g} | {res.quality}"
            )
        return

    if cmd == "debug":
        # Diagnostics
        out = ["🕵️ **Diagnóstico Avanzado**"]
        
        # 1. Global Env
        settings = get_settings()
        env_url = settings.nightscout.base_url
        out.append(f"🌍 **ENV Var URL:** `{env_url}`")
        
        # 2. User Settings (DB)
        try:
            bot_settings = await get_bot_user_settings()
            ns = bot_settings.nightscout
            out.append(f"👤 **User DB URL:** `{ns.url}` (Enabled: {ns.enabled})")
            
            # DB Discovery Detail
            engine = get_engine()
            if engine:
                async with AsyncSession(engine) as session:
                    # List all users
                    from sqlalchemy import text as sql_text
                    stmt = sql_text("SELECT user_id, settings FROM user_settings")
                    rows = (await session.execute(stmt)).fetchall()
                    out.append(f"📊 **Usuarios en DB:** {len(rows)}")
                    for r in rows:
                        uid = r.user_id
                        raw = r.settings
                        ns_raw = raw.get("nightscout", {})
                        url_raw = ns_raw.get("url", "EMPTY")
                        out.append(f"- User `{uid}`: NS_URL=`{url_raw}`")
            else:
                out.append("⚠️ **DB Desconectada.**")

            # 3. Connection Test
            target_url = ns.url or (str(env_url) if env_url else None)
            
            if target_url:
                out.append(f"📡 **Probando:** `{target_url}`")
                client = NightscoutClient(target_url, ns.token, timeout_seconds=5)
                try:
                    sgv = await client.get_latest_sgv()
                    out.append(f"✅ **Conexión EXITOSA**")
                    out.append(f"SGV: {sgv.sgv} mg/dL")
                except Exception as e:
                     out.append(f"❌ **Fallo:** `{e}`")
                finally:
                    await client.aclose()
            else:
                 out.append("🛑 **No hay URL para probar.**")

            # 4. Check DB History
            engine = get_engine()
            if engine:
                 async with AsyncSession(engine) as session:
                    from sqlalchemy import text as sql_text
                    stmt = sql_text("SELECT created_at, insulin FROM treatments ORDER BY created_at DESC LIMIT 1")
                    row = (await session.execute(stmt)).fetchone() 
                    if row:
                         out.append(f"💉 **Último Bolo (DB):** {row.insulin} U ({row.created_at.strftime('%H:%M')})")
                    else:
                         out.append(f"💉 **Último Bolo (DB):** (Vacío)")
            else:
                 out.append("⚠️ **Sin acceso a Historial DB**")

        except Exception as e:
            out.append(f"💥 **Error Script:** `{e}`")
            
        # Send without markdown to avoid parsing errors (underscores in URLs, etc.)
        await reply_text(update, context, "\n".join(out))
        return

    # --- AI Layer ---
    await context.bot.send_chat_action(chat_id=update.effective_chat.id, action=constants.ChatAction.TYPING)
    
    logger.info(f"[LLM] entering router chat_id={update.effective_chat.id} user={update.effective_user.username}")
    t0 = datetime.now()
    
    # 1. Build Context
    ctx = await context_builder.build_context(update.effective_user.username, update.effective_chat.id)
    t1 = datetime.now()
    ctx_ms = (t1 - t0).total_seconds() * 1000

    # 2. Router
    try:
        bot_reply = await router.handle_text(update.effective_user.username, update.effective_chat.id, text, ctx)
        logger.info(f"[LLM] router ok chat_id={update.effective_chat.id}")
    except Exception as e:
        # Emergency catch for router layer itself
        err_id = uuid.uuid4().hex[:8]
        logger.exception(f"[LLM] router CRIT (id={err_id})", exc_info=e)
        health.set_error(f"Router Exception: {e}", error_id=err_id, exc=e)
        await reply_text(update, context, f"⚠️ Error IA ({err_id}).")
        return

    t2 = datetime.now()
    llm_ms = (t2 - t1).total_seconds() * 1000
    
    # 3. Handle Pending Actions (Buttons)
    if bot_reply.pending_action:
        p = bot_reply.pending_action
        p["timestamp"] = datetime.now().timestamp()
        SNAPSHOT_STORAGE[p["id"]] = p
        
    # 4. Send Reply
    if bot_reply.buttons:
        reply_markup = InlineKeyboardMarkup(bot_reply.buttons)
        await reply_text(update, context, bot_reply.text, reply_markup=reply_markup)
    else:
        await reply_text(update, context, bot_reply.text)

    # 5. Send Image if present (Injection Site)
    if bot_reply.image_path:
        try:
            # Resolve path (assume relative to frontend/public if not absolute)
            img_path = Path(bot_reply.image_path)
            if not img_path.is_absolute():
                # Dynamic resolution:
                base_dir = Path("frontend/public").resolve()
                if not base_dir.exists():
                     # Try going up if we are in backend
                     base_dir = Path("../frontend/public").resolve()
                
                if not base_dir.exists():
                     # Fallback to hardcoded only if dynamic fails
                     base_dir = Path(__file__).parent.parent.parent.parent / "frontend" / "public"

                img_path = base_dir / bot_reply.image_path
            
            if img_path.exists():
                await context.bot.send_photo(
                    chat_id=update.effective_chat.id, 
                    photo=open(img_path, "rb")
                )
            else:
                logger.warning(f"Image not found: {img_path}")
        except Exception as e:
            logger.error(f"Failed to send bot image: {e}")

    # 5. Observability
    logger.info(f"AI Req: ctx={int(ctx_ms)}ms llm={int(llm_ms)}ms")
