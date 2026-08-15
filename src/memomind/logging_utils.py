#UI와 서비스에서 함께 사용하는 간단한 애플리케이션 로그 기록기입니다.

import datetime as dt


def trim_text(text: str | None, limit: int = 200) -> str:
    # 입력값을 문자열로 변환하고, 여러 공백/줄바꿈을 하나의 공백으로 정리합니다.
    # None이나 빈 값이 들어오면 빈 문자열로 처리합니다.
    compact = " ".join(str(text or "").split())

    # 정리된 문자열이 제한 길이보다 짧거나 같으면 그대로 반환합니다.
    # 제한을 초과하면 앞부분만 잘라 "..."을 붙여 길이를 줄입니다.
    return compact if len(compact) <= limit else compact[:limit] + "..."


class EventLogger:
    # UI와 서비스 계층에서 공통으로 사용하는 간단한 이벤트 로그 출력기.
    def __call__(self, stage: str, message: str = "", turn_id: int | None = None) -> None:
        # turn_id가 있으면 특정 대화 턴의 로그로 표시합니다.
        # 예: turn_id=7 -> [CHAT#007]
        # turn_id가 없으면 시스템 레벨 로그로 표시합니다.
        turn_label = f"[CHAT#{turn_id:03d}]" if turn_id is not None else "[SYSTEM]"
        # 현재 시간을 HH:MM:SS 형식으로 가져오고,
        # 대화 턴과 stage 정보를 함께 묶어 로그의 공통 prefix를 만듭니다.
        # 예: [13:30:15][CHAT#007][SEARCH]
        prefix = f"[{dt.datetime.now():%H:%M:%S}]{turn_label}[{stage}]"
        # message가 있으면 prefix 뒤에 메시지를 출력합니다.
        # message가 비어 있으면 prefix만 출력합니다.
        print(f"{prefix} {message}" if message else prefix)
