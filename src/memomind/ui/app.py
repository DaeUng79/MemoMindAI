import datetime
import asyncio
import json
from tinydb import Query
import flet as ft
import re
import webbrowser
import os
import sys
import subprocess
import threading
import time

from ..config import Settings
from ..context_service import ContextService
from ..handover import (
    build_payload,
    decode_json_data,
    extract_memos,
    payload_to_json,
    save_payload,
)
from ..llm_client import LLMClient
from ..logging_utils import EventLogger
from ..repository import MemoRepository


# ---------------------------------------------------------------------
# exe 만들기 (윈도우기준)
# pip install pyinstaller 설치
# pip install Pillow 아이콘 반영을 위해  https://icon-icons.com/ko/packs-of-icons
# pyinstaller --onefile --windowed --add-data "assets;assets" LocallLLM_flet_chat_basic.py
# pyinstaller --onefile --windowed --icon=ai.ico --add-data "assets;assets" LocallLLM_flet_chat_basic.py
# flet pack .\LocallLLM_flet_chat_basic.py --icon assets/yang_2.ico --add-data "assets;assets" --name "MemoMind_v2.0"
# ---------------------------------------------------------------------

# ---------------------------------------------------------------------
# AI모델 설정(맥북용)
# ---------------------------------------------------------------------
# llama-server -hf ggml-org/gemma-4-E2B-it-GGUF --reasoning off
# 서버 구동시 추론(생각) 단계 완전 비활성화 명령어 (--reasoning off)


Doc = Query()

# 요일 리스트 생성 (0: 월요일 ~ 6: 일요일)
weekday_list = ['월요일', '화요일', '수요일', '목요일', '금요일', '토요일', '일요일']
 
def main(page: ft.Page, settings: Settings | None = None):

    settings = settings or Settings.from_environment()

    page.title = "메모마인드(MemoMind)"
    page.padding = 20
    page.window.height = 700
    page.window.min_height = 700
    # page.window.icon = "assets/yang.ico" 
    page.update()
    # Flet 이벤트 핸들러는 작업 스레드에서 실행될 수 있으므로 Tkinter 파일
    # 선택창을 만들면(특히 macOS) 앱이 중단될 수 있다. Flet 네이티브 서비스를
    # 사용하면 데스크톱과 웹에서 동일한 이벤트 루프 안에서 안전하게 동작한다.
    received_memo_file_picker = ft.FilePicker()
    chat_messages = ft.Column(expand=True, spacing=10, scroll=ft.ScrollMode.AUTO, auto_scroll=True)
    conversation_history: list[tuple[str, str]] = []
    is_generating_response = False
    is_chat_view_active = True

    memo_dir = settings.memo_dir
    repository = MemoRepository(settings.db_path)
    repository.initialize_default()
    llm_client = LLMClient(settings.api_url, settings.model_name)
    log_event = EventLogger()
    context_service = ContextService(repository, llm_client, log_event)
    shutdown_state = {"closing": False}
    cleanup_lock = threading.Lock() 

    existing_types_cache = [] # [최적화] 문서 타입 캐싱 (매번 DB 전체 조회 방지)

    def refresh_types_cache():
        nonlocal existing_types_cache
        existing_types_cache = repository.types()
    
    refresh_types_cache() # 초기 캐시 생성
    chat_turn_counter = 0

    _last_scroll_at = 0.0
    _last_scroll_error_log_at = 0.0

    def _safe_control_update(control, name: str = "control"):
        try:
            control.update()
        except Exception as ex:
            log_event("UI", f"{name}.update skipped: {ex}")

    async def _safe_scroll_to_bottom():
        # auto_scroll=True 이지만, 일부 환경에서 scroll_to invoke가 타임아웃 날 수 있어 예외를 삼킵니다.
        nonlocal _last_scroll_at, _last_scroll_error_log_at
        if not is_chat_view_active:
            return
        if getattr(chat_messages, "page", None) is None:
            return
        now_mono = time.monotonic()
        if now_mono - _last_scroll_at < 0.12:
            return
        _last_scroll_at = now_mono
        try:
            await chat_messages.scroll_to(offset=-1)
        except Exception as ex:
            # Flet invoke 타임아웃은 간헐적으로 발생하므로 무시 (auto_scroll로 자연 스크롤 유지)
            if "TimeoutException" in str(ex):
                return
            if now_mono - _last_scroll_error_log_at >= 5:
                _last_scroll_error_log_at = now_mono
                log_event("UI", f"scroll_to skipped: {ex}")

    async def _safe_focus_user_input(reason: str = "", delays: tuple[float, ...] = (0.0,)):
        last_error = None
        if not is_chat_view_active:
            return False
        for delay in delays:
            if delay > 0:
                await asyncio.sleep(delay)
            if getattr(user_input, "page", None) is None:
                return False
            try:
                await user_input.focus()
                return True
            except Exception as ex:
                last_error = ex
        if last_error:
            context = f" ({reason})" if reason else ""
            log_event("UI", f"focus skipped{context}: {last_error}")
        return False

    async def call_llm_stream(
        prompt: str,
        output_container: ft.Markdown,
        selected_type: str,
        result_count: int,
        turn_id: int,
    ) -> str:
        prefix = output_container.value
        if selected_type == "일반답변":
            progress_message = "일반적인 답변을 생각하고 있습니다..."
        else:
            progress_message = (
                 f"등록된 {selected_type} 메모에서 {result_count} 개 자료를 참고하여 답변을 생각하고 있습니다..." 
            )

        output_container.value += progress_message
        _safe_control_update(output_container, "bot_text_control")
        log_event(
            "STREAM",
            f"답변 요청 시작 / 유형={selected_type} / 참고={result_count}건",
            turn_id,
        )

        collected = ""
        is_first_chunk = True
        pending = ""
        last_flush_at = time.monotonic()

        async def flush(force: bool = False):
            nonlocal pending, last_flush_at
            if not pending:
                return
            now_mono = time.monotonic()
            if not force and len(pending) < 24 and (now_mono - last_flush_at) < 0.06:
                return
            output_container.value += pending
            pending = ""
            _safe_control_update(output_container, "bot_text_control")
            last_flush_at = now_mono
            await _safe_scroll_to_bottom()

        async for chunk in llm_client.stream(prompt):
            if is_first_chunk:
                output_container.value = prefix
                is_first_chunk = False
                log_event("STREAM", "첫 응답 수신", turn_id)

            collected += chunk
            pending += chunk
            await flush(force=False)

        await flush(force=True)

        if not collected:
            raise RuntimeError("LLM 서버가 내용 없는 스트리밍 응답을 반환했습니다.")

        log_event("STREAM", f"답변 완료 / {len(collected)}자", turn_id)

        return collected

    # -----------------------------------------------------------------
    # 채팅 메시지 영역 및 대화 관리 로직
    # -----------------------------------------------------------------

    def show_chat_view(e): # 클릭 이벤트(e)를 인자로 받도록 수정 쳇봇 화면으로 돌아가기 위해 필요
        nonlocal is_chat_view_active
        is_chat_view_active = True
        main_area.controls = [
            ft.Container(height=25),
            chat_messages,
            ft.Row([user_input, reset_button], spacing=10),
        ]
        page.update()

    def add_chat(role: str, text: str = ""):
        user_avatar_url = "/yang.png"
        ai_avatar_url = "/korea.png"
        
        is_user = role == "user"
        avatar_src = user_avatar_url if is_user else ai_avatar_url

        # 아바타 배경을 투명(TRANSPARENT)으로 설정
        avatar = ft.CircleAvatar(
            foreground_image_src=avatar_src,
            radius=18,
            bgcolor=ft.Colors.TRANSPARENT, # 아바타 원형 배경을 투명하게 설정
        )
 
        def handle_link_click(e): # 답변내용 중 링크 내용 클릭 시 URL 열기
            log_event("LINK", f"클릭된 링크: {e.data}")
            webbrowser.open(e.data) 

        text_control = ft.Markdown(
            text,
            selectable=True,
            extension_set=ft.MarkdownExtensionSet.GITHUB_WEB,
            on_tap_link=handle_link_click,
            expand=True,
        )

        # 메시지 컨테이너 배경도 투명하게 하거나 반투명하게 설정 가능
        chat_row = ft.Row(
            controls=[
                avatar,
                ft.Container(
                    content=text_control,
                    padding=10,
                    expand=True,
                    bgcolor=ft.Colors.TRANSPARENT, # 메시지 박스 배경도 투명하게 설정
                ),
            ],
            vertical_alignment=ft.CrossAxisAlignment.START,
        )

        chat_messages.controls.append(chat_row)
        page.update()
        return text_control
    
    # -----------------------------------------------------------------
    # 사용자 입력 처리 (메시지 교체 및 일반 답변 로직)
    # -----------------------------------------------------------------

    async def restore_user_input_focus():
        _safe_control_update(user_input, "user_input")
        await _safe_focus_user_input("restore", delays=(0.02, 0.1, 0.25, 0.6))

    async def send_message(event: ft.ControlEvent): 
        nonlocal chat_turn_counter, is_generating_response
        if is_generating_response:
            await _safe_focus_user_input("already_generating")
            return

        user_prompt = user_input.value.strip()
        if not user_prompt: return
        is_generating_response = True
        chat_turn_counter += 1
        turn_id = chat_turn_counter

        
        add_chat("user", user_prompt)
        user_input.value = ""
        page.update()
        await _safe_scroll_to_bottom()

        now = datetime.datetime.now()
        now_str = now.strftime(f"%Y년 %m월 %d일 {weekday_list[now.weekday()]} %H시 %M분")
        # 1. 초기 메시지 표시
        bot_text_control = add_chat("assistant", "")
        # bot_text_control.value = f"현재 시각은 {now_str}입니다."
        page.update()

        async def get_response():
            nonlocal is_generating_response
            try:
                # DB 검색 전, 사용자에게 분석 중임을 알리는 메시지를 표시합니다.
                bot_text_control.value = "질문을 분석하고 있습니다..."
                page.update()

                # 2. DB 검색
                search_result = await context_service.search(user_prompt, turn_id)
                db_context = search_result.context
            
                # DB 검색이 완료되면 메시지를 초기화하여 다음 단계(LLM 호출)를 준비합니다.
                bot_text_control.value = ""

                # [최적화] 대화 기록이 너무 길어지면 저사양 PC에서 느려지므로 최근 3턴(6개 메시지)만 전송
                recent_history = conversation_history[-8:] if len(conversation_history) > 6 else conversation_history
                history_str = "\n".join([f"{role}: {text}" for role, text in recent_history])

                if db_context:
                    instruction = (
                        "검색된 메모를 근거로 사용자 질문에 친절히 답변해주세요."
                        "질문과 직접 관련된 핵심 정보를 안내하고, 링크가 포함되어 있으면 함께 제공해주세요."
                    )
                    prompt_head = (
                        f"인스트럭션 : {instruction}\n"
                        f"사용자 질문 : {user_prompt}\n"
                        f"이전 대화 기록 : {history_str}\n"
                        "참고 메모 :\n"
                    )
                    final_prompt = prompt_head + db_context
                else:
                    instruction = (
                        f"지금은 ({now_str}) 입니다. 직장인에게 힘이되어 주세요."
                    )
                    final_prompt = (
                        f"인스트럭션 : {instruction}\n"
                        f"사용자 질문 : {user_prompt}\n"
                        f"이전 대화 기록 : {history_str}"
                    )
                log_event("HISTORY", f"최근 대화 {len(recent_history)}개", turn_id)
                
                # 4. 분류 타입과 DB 검색 건수를 표시한 뒤 스트리밍 시작
                bot_response = await call_llm_stream(
                    final_prompt,
                    bot_text_control,
                    selected_type=search_result.selected_type,
                    result_count=search_result.result_count,
                    turn_id=turn_id,
                )
                
                conversation_history.append(("user", user_prompt))
                conversation_history.append(("assistant", bot_response))
                
            except Exception as e:
                bot_text_control.value = f"인공지능 서버에 연결되지 않았습니다. 조금 후 시도해 주세요({str(e)})"
                log_event("ERROR", str(e), turn_id)
            finally:
                is_generating_response = False
                page.update()
                page.run_task(restore_user_input_focus)

        page.run_task(get_response)

    def reset_conversation(e=None):  # 대화 초기화
        chat_messages.controls.clear()
        conversation_history.clear()
        log_event("RESET", "대화내용 초기화")
        
        add_chat("assistant", f"메모마인드 AI 어시스턴스입니다. 무엇을 도와드릴까요?")
        page.update()
    

    user_input = ft.TextField(
        label="궁금한 내용을 입력하세요",
        expand=True,
        multiline=True,      # 여러 줄 입력 가능하게 설정
        shift_enter=True,    # Enter는 전송, Shift+Enter는 줄바꿈으로 설정
        autofocus=True,
        can_request_focus=True,
        on_submit=send_message,
    )

    reset_button = ft.Button("대화초기화", on_click=reset_conversation)

    # -----------------------------------------------------------------
    # 업무자료 입력/저장 영역
    # -----------------------------------------------------------------

    document_input = ft.TextField(
        label="프로젝트명 입력",
        width=160,)       
    document_input2 = ft.TextField(
        label="메모내용 입력",
        multiline=True,
        expand=True,
    )

    def update_input_fields_theme():
        is_dark = page.theme_mode == ft.ThemeMode.DARK

        if is_dark:
            border_color = ft.Colors.BLUE_GREY_300
            focused_border_color = ft.Colors.CYAN_300
            bg_color = ft.Colors.with_opacity(0.08, ft.Colors.WHITE)
            text_color = ft.Colors.WHITE
            label_color = ft.Colors.BLUE_100
            cursor_color = ft.Colors.CYAN_200
        else:
            border_color = ft.Colors.BLUE_GREY_400
            focused_border_color = ft.Colors.INDIGO_500
            bg_color = ft.Colors.WHITE
            text_color = ft.Colors.BLACK
            label_color = ft.Colors.BLUE_GREY_700
            cursor_color = ft.Colors.INDIGO_600

        for field in (user_input, document_input, document_input2):
            field.border_color = border_color
            field.focused_border_color = focused_border_color
            field.bgcolor = bg_color
            field.color = text_color
            field.cursor_color = cursor_color
            field.label_style = ft.TextStyle(color=label_color)
            field.border_radius = 10
    DEFAULT_RECENT_LIMIT = 5
    TYPE_FILTER_INITIAL_LIMIT = 10
    MEMO_LOAD_STEP = 20
    DOC_VIEW_KEEP = object()
    selected_doc_type: str | None = None
    memo_display_limit = DEFAULT_RECENT_LIMIT
    sidebar_type_buttons = ft.Column(
        spacing=6,
        tight=True,
    )

    def refresh_sidebar_type_buttons():
        is_dark = page.theme_mode == ft.ThemeMode.DARK

        def _link_text(label: str, selected: bool) -> ft.Text:
            selected_color = ft.Colors.CYAN_200 if is_dark else ft.Colors.BLUE_700
            normal_color = ft.Colors.BLUE_100 if is_dark else ft.Colors.BLUE_GREY_700
            return ft.Text(
                label,
                size=12,
                weight=ft.FontWeight.W_600 if selected else ft.FontWeight.W_400,
                color=selected_color if selected else normal_color,
            )

        inline_controls: list[ft.Control] = [
            ft.GestureDetector(
                content=_link_text("전체", selected_doc_type is None),
                on_tap=lambda e: show_doc_view(e, selected_type=None, limit=DEFAULT_RECENT_LIMIT),
            )
        ]

        for d_type in sorted(existing_types_cache):
            divider_color = ft.Colors.with_opacity(0.45, ft.Colors.WHITE) if is_dark else ft.Colors.BLUE_GREY_400
            inline_controls.append(ft.Text("|", size=12, color=divider_color))
            inline_controls.append(
                ft.GestureDetector(
                    content=_link_text(d_type, selected_doc_type == d_type),
                    on_tap=lambda e, t=d_type: show_doc_view(
                        e, selected_type=t, limit=TYPE_FILTER_INITIAL_LIMIT
                    ),
                )
            )

        if len(inline_controls) == 1:
            empty_color = ft.Colors.BLUE_100 if is_dark else ft.Colors.BLUE_GREY_500
            inline_controls = [ft.Text("등록된 등록메모가 없습니다.", size=12, color=empty_color)]

        sidebar_type_buttons.controls = [
            ft.Row(
                controls=inline_controls,
                wrap=True,
                spacing=4,
                run_spacing=4,
            )
        ]

    def save_doc(e):
        doc_type = document_input.value.strip()
        doc_material = document_input2.value.strip()

        if doc_type and doc_material:
            repository.insert(doc_type, doc_material)
            refresh_types_cache() # 데이터 변경 시 캐시 갱신

        document_input.value = ""
        document_input2.value = ""
        show_doc_view(selected_type=selected_doc_type, limit=memo_display_limit) # 저장 후 목록 갱신

    def search_doc(e):
        search_type_query = document_input.value.strip()
        search_content_query = document_input2.value.strip()

        # 검색어가 없으면 전체 목록을 보여주는 기본 화면으로 돌아감
        if not search_type_query and not search_content_query:
            show_doc_view(selected_type=selected_doc_type, limit=memo_display_limit)
            return

        def custom_search(doc):
            type_match = True
            content_match = True
            
            doc_type = doc.get('document_type', '').lower()
            doc_content = doc.get('assistant', '').lower()

            if search_type_query:
                type_match = search_type_query.lower() in doc_type
            
            if search_content_query:
                content_match = search_content_query.lower() in doc_content
            
            return type_match and content_match

        results = repository.search(custom_search)
        show_doc_view(search_results=results, selected_type=selected_doc_type, limit=memo_display_limit)

    # 업무메모 확인에서 수정
    def save_inline(doc_id: int, field: ft.TextField, button: ft.IconButton):
        """저장 후 아이콘을 체크로 변경."""
        cleaned_value = re.sub(r'^\[.*?\]', '', field.value).strip()

        repository.update_content(doc_id, cleaned_value)

        button.icon = ft.Icons.CHECK
        button.icon_color = "green"
        button.tooltip = "저장 완료"
        button.update()

    def confirm_save_item(doc_id: int, field: ft.TextField, button: ft.IconButton):
        def on_confirm(e):
            page.pop_dialog()
            save_inline(doc_id, field, button)

        page.show_dialog(
            ft.AlertDialog(
                modal=True,
                title=ft.Text("수정 확인"),
                content=ft.Text("수정하시겠습니까?"),
                actions=[
                    ft.TextButton("취소", on_click=lambda e: page.pop_dialog()),
                    ft.TextButton("수정", on_click=on_confirm),
                ],
                actions_alignment=ft.MainAxisAlignment.END,
            )
        )

    # 업무메모 확인에서 삭제
    def delete_item(doc_id: int, refresh_func):
        repository.remove(doc_id)
        refresh_types_cache() # 데이터 변경 시 캐시 갱신
        if refresh_func:
            refresh_func()

    def confirm_delete_item(doc_id: int, refresh_func):
        def on_confirm(e):
            page.pop_dialog()
            delete_item(doc_id, refresh_func)

        page.show_dialog(
            ft.AlertDialog(
                modal=True,
                title=ft.Text("삭제 확인"),
                content=ft.Text("삭제하시겠습니까?"),
                actions=[
                    ft.TextButton("취소", on_click=lambda e: page.pop_dialog()),
                    ft.TextButton("삭제", on_click=on_confirm),
                ],
                actions_alignment=ft.MainAxisAlignment.END,
            )
        )

    def show_message(message: str):
        page.show_dialog(
            ft.AlertDialog(
                modal=True,
                title=ft.Text("알림"),
                content=ft.Text(message),
                actions=[
                    ft.TextButton("확인", on_click=lambda e: page.pop_dialog()),
                ],
                actions_alignment=ft.MainAxisAlignment.END,
            )
        )

    def build_type_memo_payload() -> dict:
        return build_payload(repository.all(), selected_doc_type)

    def open_export_folder(e=None):
        try:
            if sys.platform == "win32":
                os.startfile(str(memo_dir))
            elif sys.platform == "darwin":
                subprocess.Popen(["open", str(memo_dir)])
            else:
                subprocess.Popen(["xdg-open", str(memo_dir)])
        except Exception as error:
            show_message(f"저장폴더를 열지 못했습니다.\n{error}")

    def import_received_memos(raw_json: str) -> tuple[int, int]:
        payload = json.loads(raw_json)
        memos = extract_memos(payload)

        inserted_count = 0
        skipped_count = 0
        imported_at = datetime.datetime.now().isoformat(timespec="seconds")

        for memo in memos:
            if not isinstance(memo, dict):
                skipped_count += 1
                continue

            doc_type = str(memo.get("document_type") or memo.get("business_type_name") or "").strip()
            content = str(memo.get("assistant", "")).strip()
            timestamp = str(memo.get("timestamp", "")).strip() or imported_at

            if not doc_type or not content:
                skipped_count += 1
                continue

            already_exists = repository.contains(
                (Doc.document_type == doc_type)
                & (Doc.assistant == content)
                & (Doc.timestamp == timestamp)
            )

            if already_exists:
                skipped_count += 1
                continue

            repository.insert(
                doc_type,
                content,
                timestamp=timestamp,
                imported_at=imported_at,
            )
            inserted_count += 1

        refresh_types_cache()
        return inserted_count, skipped_count

    def copy_type_memos(e=None):
        payload = build_type_memo_payload()
        if payload["count"] == 0:
            show_message("추출할 등록메모가 없습니다.")
            return

        page.clipboard.set(payload_to_json(payload))
        show_message(f"등록메모 {payload['count']}개를 JSON 형식으로 복사했습니다.")

    def save_type_memos_as_json(e=None):
        payload = build_type_memo_payload()
        if payload["count"] == 0:
            show_message("추출할 등록메모가 없습니다.")
            return

        prefix = f"등록메모_{selected_doc_type}" if selected_doc_type else "전체등록메모"
        export_path = save_payload(payload, memo_dir, prefix)
        show_message(f"JSON 파일로 저장했습니다.\n{export_path}")

    def extract_type_memos(e=None):
        payload = build_type_memo_payload()
        extracted_text = payload_to_json(payload)

        if payload["count"] == 0:
            show_message("추출할 등록메모가 없습니다.")
            return

        title = (
            f"[{selected_doc_type}] 등록메모 JSON 추출 ({payload['count']}개)"
            if selected_doc_type
            else f"전체 등록메모별 JSON 추출 ({payload['count']}개)"
        )

        extract_field = ft.TextField(
            value=extracted_text,
            multiline=True,
            read_only=True,
            min_lines=12,
            max_lines=18,
            text_size=13,
        )

        dialog = ft.AlertDialog(
            modal=True,
            title=ft.Text(title),
            content=ft.Container(
                content=extract_field,
                width=720,
                height=420,
            ),
            actions=[
                ft.TextButton("복사", on_click=copy_type_memos),
                ft.TextButton("데이터 저장", on_click=save_type_memos_as_json),
                ft.TextButton("폴더열기", on_click=open_export_folder),
                ft.TextButton("닫기", on_click=lambda e: close_extract_dialog(dialog)),
            ],
            actions_alignment=ft.MainAxisAlignment.END,
        )

        page.show_dialog(dialog)

    def open_received_memo_dialog(e=None):
        status_text = ft.Text("", size=13, color=ft.Colors.BLUE_700, visible=False)
        progress_ring = ft.ProgressRing(width=18, height=18, visible=False)

        def set_register_state(button, *, busy: bool, message: str = ""):
            button.disabled = busy
            progress_ring.visible = busy
            status_text.value = message
            status_text.visible = bool(message)
            page.update()

        async def register_json_file(event=None):
            register_button = event.control
            set_register_state(register_button, busy=True, message="JSON 파일을 선택해 주세요.")

            try:
                selected_files = await received_memo_file_picker.pick_files(
                    dialog_title="받은 메모 JSON 선택",
                    initial_directory=str(memo_dir),
                    file_type=ft.FilePickerFileType.CUSTOM,
                    allowed_extensions=["json"],
                    allow_multiple=False,
                    with_data=True,
                )
            except Exception as error:
                set_register_state(register_button, busy=False, message="파일 선택창을 열지 못했습니다.")
                show_message(f"파일 선택창을 열지 못했습니다.\n{error}")
                return

            if not selected_files:
                set_register_state(register_button, busy=False)
                return

            selected_file = selected_files[0]
            set_register_state(register_button, busy=True, message="등록 중입니다. 잠시만 기다려 주세요.")

            try:
                file_data = selected_file.bytes
                if file_data is None and selected_file.path:
                    with open(selected_file.path, "rb") as file:
                        file_data = file.read()
                if file_data is None:
                    raise ValueError("선택한 파일의 내용을 가져오지 못했습니다.")
                raw_json = decode_json_data(file_data)
            except (OSError, UnicodeDecodeError, ValueError) as error:
                set_register_state(register_button, busy=False, message="파일을 읽지 못했습니다.")
                show_message(f"JSON 파일을 읽지 못했습니다.\n{error}")
                return

            try:
                inserted_count, skipped_count = import_received_memos(raw_json)
            except json.JSONDecodeError as error:
                set_register_state(register_button, busy=False, message="JSON 형식이 올바르지 않습니다.")
                show_message(f"JSON 형식이 올바르지 않습니다.\n{error}")
                return
            except ValueError as error:
                set_register_state(register_button, busy=False, message="등록할 메모를 찾지 못했습니다.")
                show_message(str(error))
                return
            except Exception as error:
                set_register_state(register_button, busy=False, message="메모 등록 중 오류가 발생했습니다.")
                show_message(f"메모를 등록하지 못했습니다.\n{error}")
                return

            status_text.value = "등록이 완료되었습니다."
            page.update()
            page.pop_dialog()
            show_doc_view(selected_type=selected_doc_type, limit=memo_display_limit)
            show_message(
                f"받은 메모 등록 완료\n"
                f"등록: {inserted_count}개 / 건너뜀: {skipped_count}개"
            )

        dialog = ft.AlertDialog(
            modal=True,
            title=ft.Text("받은 메모 등록"),
            content=ft.Container(
                content=ft.Column(
                    [
                        ft.Text(
                            "추출된 JSON 파일을 선택하면 등록메모별로 메모가 즉시 등록됩니다.",
                            size=13,
                            color=ft.Colors.BLUE_GREY_700,
                        ),
                        ft.FilledButton(
                            "JSON 파일 선택 및 등록",
                            icon=ft.Icons.UPLOAD_FILE,
                            on_click=register_json_file,
                        ),
                        ft.Row(
                            [progress_ring, status_text],
                            spacing=10,
                            vertical_alignment=ft.CrossAxisAlignment.CENTER,
                        ),
                    ],
                    spacing=14,
                    tight=True,
                    horizontal_alignment=ft.CrossAxisAlignment.STRETCH,
                ),
                width=420,
            ),
            actions=[
                ft.TextButton("닫기", on_click=lambda e: close_extract_dialog(dialog)),
            ],
            actions_alignment=ft.MainAxisAlignment.END,
        )

        page.show_dialog(dialog)

    def open_handover_menu(e=None):
        selected_type_name = selected_doc_type or "전체"
        type_label = (
            f"{selected_doc_type} 데이터 추출"
            if selected_doc_type
            else "전체 등록메모 데이터 추출"
        )

        dialog = ft.AlertDialog(
            modal=True,
            title=ft.Text("인수 인계"),
            content=ft.Container(
                content=ft.Column(
                    [
                        ft.Text(
                            f"선택된 등록메모: {selected_type_name}",
                            size=13,
                            weight=ft.FontWeight.W_600,
                            color=ft.Colors.BLUE_GREY_700,
                        ),
                        ft.FilledButton(
                            type_label,
                            icon=ft.Icons.DOWNLOAD,
                            on_click=lambda e: (page.pop_dialog(), extract_type_memos()),
                        ),
                        ft.OutlinedButton(
                            "받은 메모 등록",
                            icon=ft.Icons.UPLOAD_FILE,
                            on_click=lambda e: (page.pop_dialog(), open_received_memo_dialog()),
                        ),
                    ],
                    spacing=10,
                    tight=True,
                    horizontal_alignment=ft.CrossAxisAlignment.STRETCH,
                ),
                width=320,
            ),
            actions=[
                ft.TextButton("닫기", on_click=lambda e: close_extract_dialog(dialog)),
            ],
            actions_alignment=ft.MainAxisAlignment.END,
        )

        page.show_dialog(dialog)

    def close_extract_dialog(dialog: ft.AlertDialog):
        page.pop_dialog()

    # 메모 리스트 UI 생성 함수 (재사용을 위해 분리)
    def get_memo_controls(refresh_func, items_to_display=None):
        items = items_to_display if items_to_display is not None else repository.all()
        items.sort(key=lambda x: x.get("timestamp", ""), reverse=True)

        controls_list = []
        current_date = None 

        for item in items:
            doc_id = item.doc_id
            doc_type = item.get("document_type", "")
            content = item.get("assistant", "")
            timestamp = item.get("timestamp", "")

            date_part = timestamp[:10] if len(timestamp) >= 10 else "날짜 없음"
            time_part = timestamp[11:19] if len(timestamp) >= 19 else ""

            if date_part != current_date:
                current_date = date_part
                controls_list.append(
                    ft.Container(
                        content=ft.Text(
                            f"📅 {current_date}",
                            size=15,
                            weight=ft.FontWeight.BOLD,
                            color=ft.Colors.BLUE_GREY,
                        ),
                        padding=ft.Padding.only(top=20, bottom=5),
                    )
                )

            content_field = ft.TextField(
                value="[" + doc_type + "] " + content,
                text_size=14,
                multiline=True,
                border=ft.InputBorder.NONE,
                expand=True,
            )

            save_button = ft.IconButton(
                icon=ft.Icons.EDIT,
                icon_color=ft.Colors.BLUE,
                icon_size=20,
                tooltip="수정",
            )

            delete_button = ft.IconButton(
                icon=ft.Icons.DELETE,
                icon_color=ft.Colors.RED,
                icon_size=20,
                tooltip="삭제",
                on_click=lambda e, id=doc_id: confirm_delete_item(id, refresh_func),
            )

            save_button.on_click = (
                lambda e, id=doc_id, field=content_field, btn=save_button: confirm_save_item(id, field, btn)
            )

            controls_list.append(
                ft.Card(
                    content=ft.Container(
                        padding=15,
                        content=ft.Column(
                            [
                                content_field,
                                ft.Row(
                                    [
                                        ft.TextField(
                                            value=time_part,
                                            text_size=12,
                                            color=ft.Colors.GREY,
                                            border=ft.InputBorder.NONE,
                                            dense=True,
                                            content_padding=0,
                                            width=150,
                                            read_only=True,
                                        ),
                                        ft.Row(
                                            [save_button, delete_button],
                                            spacing=0,
                                        ),
                                    ],
                                    alignment=ft.MainAxisAlignment.SPACE_BETWEEN,
                                ),
                            ]
                        ),
                    )
                )
            )
        return controls_list

    def show_doc_view(e=None, search_results=None, selected_type=DOC_VIEW_KEEP, limit=None):
        nonlocal selected_doc_type, memo_display_limit, is_chat_view_active
        is_chat_view_active = False
        save_button = ft.Button("저장", on_click=save_doc)
        search_button = ft.Button("검색", on_click=search_doc)
        is_dark = page.theme_mode == ft.ThemeMode.DARK

        if selected_type is not DOC_VIEW_KEEP:
            selected_doc_type = selected_type
 
        if limit is not None:
            memo_display_limit = limit

        is_search = search_results is not None

        if not is_search:
            # 검색이 아닐 때만 입력 필드 초기화
            document_input.value = ""
            document_input2.value = ""

        if is_search:
            source_items = list(search_results)
        elif selected_doc_type:
            source_items = repository.search(Doc.document_type == selected_doc_type)
        else:
            source_items = repository.all()

        source_items.sort(key=lambda x: x.get("timestamp", ""), reverse=True)
        total_count = len(source_items)
        visible_items = source_items[:memo_display_limit]

        def refresh_current_view():
            show_doc_view(selected_type=DOC_VIEW_KEEP, limit=memo_display_limit)

        memo_controls = get_memo_controls(refresh_current_view, items_to_display=visible_items)

        if is_search:
            list_title = f"검색 결과 ({total_count}개)"
        elif selected_doc_type:
            list_title = f"[{selected_doc_type}] 메모 목록 ({total_count}개)"
        else:
            list_title = f"최근 메모 목록 ({total_count}개)"

        refresh_sidebar_type_buttons()

        selected_bg = ft.Colors.with_opacity(0.35, ft.Colors.CYAN_700) if is_dark else ft.Colors.BLUE_100
        selected_fg = ft.Colors.WHITE if is_dark else ft.Colors.BLUE_900
        selected_border = ft.Colors.CYAN_200 if is_dark else ft.Colors.BLUE_300
        unselected_fg = ft.Colors.BLUE_100 if is_dark else ft.Colors.BLUE_GREY_700
        unselected_border = ft.Colors.with_opacity(0.55, ft.Colors.BLUE_100) if is_dark else ft.Colors.BLUE_GREY_300

        def type_button_style(is_selected: bool) -> ft.ButtonStyle:
            return ft.ButtonStyle(
                bgcolor=selected_bg if is_selected else None,
                color=selected_fg if is_selected else unselected_fg,
                side=ft.BorderSide(
                    1,
                    selected_border if is_selected else unselected_border,
                ),
                padding=ft.Padding(left=10, right=10, top=4, bottom=4),
                visual_density=ft.VisualDensity.COMPACT,
            )

        type_buttons = [
            ft.OutlinedButton(
                "전체",
                on_click=lambda e: show_doc_view(e, selected_type=None, limit=DEFAULT_RECENT_LIMIT),
                style=type_button_style(selected_doc_type is None),
            )
        ]
        for d_type in sorted(existing_types_cache):
            type_buttons.append(
                ft.OutlinedButton(
                    d_type,
                    on_click=lambda e, t=d_type: show_doc_view(
                        e, selected_type=t, limit=TYPE_FILTER_INITIAL_LIMIT
                    ),
                    style=type_button_style(selected_doc_type == d_type),
                )
            )

        show_more_button = None
        if total_count > memo_display_limit:
            show_more_button = ft.OutlinedButton(
                f"더보기 (+{MEMO_LOAD_STEP})",
                on_click=lambda e: show_doc_view(
                    e, selected_type=DOC_VIEW_KEEP, limit=memo_display_limit + MEMO_LOAD_STEP
                ),
            )

        main_area.controls = [
            ft.Container(height=0.0), 
            ft.Text("메모 관리(Memo Management)", size=24, weight=ft.FontWeight.BOLD),
            ft.Text("프로젝트별 필요한 내용 연락처, 담당자, 사이트 링크, 사업추진 등 메모내용을 등록할 수 있습니다.", size=14),
            ft.Divider(),
            ft.Row([document_input, document_input2, save_button, search_button], spacing=10),
            ft.Divider(),
            ft.Row(
                [
                    ft.Container(
                        content=ft.Row(
                            controls=type_buttons,
                            wrap=True,
                            spacing=8,
                            run_spacing=6,
                        ),
                        expand=True,
                    ),
                    ft.Container(
                        content=ft.FilledButton(
                            "인수 인계",
                            icon=ft.Icons.IMPORT_EXPORT,
                            on_click=open_handover_menu,
                            width=150,
                        ),
                        width=165,
                        alignment=ft.Alignment(1, -1),
                    ),
                ],
                spacing=12,
                vertical_alignment=ft.CrossAxisAlignment.START,
            ),
            ft.Text(list_title, size=20, weight=ft.FontWeight.BOLD),
            ft.Column(memo_controls, scroll=ft.ScrollMode.AUTO, expand=True),
            ft.Row([show_more_button], alignment=ft.MainAxisAlignment.CENTER) if show_more_button else ft.Container(),
            ]
        page.update()

    # -----------------------------------------------------------------
    # 사이드바 & 메인 영역
    # -----------------------------------------------------------------
    
    def Google_url(e):
        webbrowser.open("https://www.google.com/search?sourceid=chrome&udm=50&aep=42&source=chrome.crn.rb&sei=Pnyuaaj7O7uMvr0PsMuZaA")
        
    def GPT_url(e):
        webbrowser.open("https://chatgpt.com")

    def moel_url(e):
        webbrowser.open("https://ai.moel.go.kr/llc/labor-law-chat")

    def update_sidebar_type_card_theme():
        if page.theme_mode == ft.ThemeMode.DARK:
            sidebar_type_card.bgcolor = ft.Colors.with_opacity(0.22, ft.Colors.BLUE_GREY_900)
            sidebar_type_card.border = ft.Border.all(1, ft.Colors.with_opacity(0.55, ft.Colors.BLUE_200))
            sidebar_type_title_icon.color = ft.Colors.CYAN_200
            sidebar_type_title_text.color = ft.Colors.CYAN_200
        else:
            sidebar_type_card.bgcolor = ft.Colors.BLUE_GREY_50
            sidebar_type_card.border = ft.Border.all(1, ft.Colors.BLUE_GREY_100)
            sidebar_type_title_icon.color = ft.Colors.BLUE_GREY_700
            sidebar_type_title_text.color = ft.Colors.BLUE_GREY_700

    def update_sidebar_nav_buttons_theme():
        is_dark = page.theme_mode == ft.ThemeMode.DARK
        border_color = ft.Colors.CYAN_200 if is_dark else ft.Colors.BLUE_GREY_300
        text_color = ft.Colors.BLUE_100 if is_dark else ft.Colors.BLUE_GREY_800
        bg_color = ft.Colors.with_opacity(0.15, ft.Colors.BLUE_GREY_800) if is_dark else None

        style = ft.ButtonStyle(
            color=text_color,
            bgcolor=bg_color,
            side=ft.BorderSide(1.2, border_color),
            padding=ft.Padding(left=12, right=12, top=8, bottom=8),
        )
        sidebar_chat_button.style = style
        sidebar_memo_button.style = style
    
    # 테마 전환 함수 정의
    def toggle_theme(e):
        if page.theme_mode == ft.ThemeMode.LIGHT:
            page.theme_mode = ft.ThemeMode.DARK
            page.dark_theme = ft.Theme(color_scheme_seed=ft.Colors.INDIGO)
            theme_button.icon = ft.Icons.LIGHT_MODE_OUTLINED
            theme_label.value = "Dark Mode"  # 글자 변경
            theme_button.tooltip = "라이트 모드로 전환"
        else:
            page.theme_mode = ft.ThemeMode.LIGHT
            page.light_theme = ft.Theme(color_scheme_seed=ft.Colors.INDIGO)
            theme_button.icon = ft.Icons.DARK_MODE_OUTLINED
            theme_label.value = "Light Mode"  # 글자 변경
            theme_button.tooltip = "다크 모드로 전환"
        update_sidebar_type_card_theme()
        update_sidebar_nav_buttons_theme()
        update_input_fields_theme()
        refresh_sidebar_type_buttons()
        page.update()


    sidebar_chat_button = ft.OutlinedButton("메모마인드 AI 어시스턴스", on_click=show_chat_view)
    sidebar_memo_button = ft.OutlinedButton("업무메모 관리", on_click=show_doc_view)
    sidebar_type_title_icon = ft.Icon(ft.Icons.LIST_ALT, size=16)
    sidebar_type_title_text = ft.Text("등록메모", size=13, weight=ft.FontWeight.BOLD)
 
    # 초기 테마 및 테마 선택 버튼 정의
    page.theme_mode = ft.ThemeMode.LIGHT
    page.theme = ft.Theme(color_scheme_seed="deep_purple")  
    theme_label = ft.Text("Dark Mode", size=14)

    theme_button = ft.IconButton(
        icon=ft.Icons.DARK_MODE_OUTLINED,
        tooltip="모드 전환",
        on_click=toggle_theme,
    )

    # -----------------------------------------------------------------
    # LLM HTTP 클라이언트 관리 코드
    # -----------------------------------------------------------------
    def _close_http_client():
        if llm_client.is_closed:
            return

        try:
            asyncio.run(llm_client.close())
            return
        except RuntimeError:
            done = threading.Event()

            def _runner():
                try:
                    asyncio.run(llm_client.close())
                except Exception:
                    pass
                finally:
                    done.set()

            threading.Thread(target=_runner, daemon=True).start()
            done.wait(3)
        except Exception:
            pass

    def cleanup_resources(reason: str = "shutdown"):
        with cleanup_lock:
            if shutdown_state["closing"]:
                return
            shutdown_state["closing"] = True

        log_event("SHUTDOWN", reason)
        _close_http_client()
        repository.close()

    def request_cleanup(reason: str):
        def _cleanup_then_exit():
            cleanup_resources(reason)
            if getattr(sys, "frozen", False):
                time.sleep(0.2)
                os._exit(0)

        threading.Thread(target=_cleanup_then_exit, daemon=True).start()

    page.on_disconnect = lambda e: request_cleanup("disconnect")
    page.on_close = lambda e: request_cleanup("close")

    # -----------------------------------------------------------------
    # 메인화면
    # -----------------------------------------------------------------

    sidebar_type_card = ft.Container(
        padding=10,
        border_radius=12,
        content=ft.Column(
            [
                ft.Row(
                    [sidebar_type_title_icon, sidebar_type_title_text],
                    spacing=6,
                ),
                sidebar_type_buttons,
            ],
            spacing=8,
        ),
    )

    sidebar = ft.Container(
        width=240,
        padding=10,
        content=ft.Column(
            [
                # 글자 자체를 가운데 정렬
                ft.Text("MemoMind", size=24, weight=ft.FontWeight.BOLD, text_align=ft.TextAlign.CENTER),
                ft.Text("끄적임은 자유롭게, 정리는 AI가", size=14, text_align=ft.TextAlign.CENTER),
                
                ft.Divider(),
                sidebar_chat_button,
                sidebar_memo_button,
                sidebar_type_card,
                ft.Container(expand=True),
                ft.Divider(),
                ft.Button("Google AI 바로가기", on_click=Google_url),
                ft.Button("ChatGPT 바로가기", on_click=GPT_url),
                ft.Button("AI노동법 챗봇 바로가기", on_click=moel_url),

                ft.Row([theme_button, theme_label]),
                ft.Container(
                    content=ft.Text("개선요청 : 오대웅(odw0902@korea.kr)", size=12, text_align=ft.TextAlign.CENTER),
                    alignment=ft.Alignment(0, 0) 
                ),
            ],
        spacing=10,
        horizontal_alignment=ft.CrossAxisAlignment.STRETCH,
        ),
    )

    main_area = ft.Column(
        [
            ft.Container(height=25),  # 버튼 위에 공백 추가
            chat_messages,
            ft.Row([user_input, reset_button], spacing=10),
        ],
        expand=True,
    )

    update_sidebar_type_card_theme()
    update_sidebar_nav_buttons_theme()
    update_input_fields_theme()
    refresh_sidebar_type_buttons()
    page.add(ft.Row([sidebar, main_area], expand=True))
    reset_conversation()

