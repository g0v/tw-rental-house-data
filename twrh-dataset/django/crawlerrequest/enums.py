from enum import IntEnum

class RequestType(IntEnum):
    LIST = 0
    DETAIL = 1

class RequestStatus(IntEnum):
    '''queue 顯式狀態機（architecture-roadmap 1-1）。

    pending → in_flight → done | failed(n) | dead
    「刪列＝完成」廢除：終結列留存，收工鐵律 seeds == terminals
    （done + dead == seeds，且無 pending / in_flight / failed 殘留）。
    值 >= TERMINAL_MIN 即終結態；failed 可再認領重試，達 attempts
    上限轉 dead。
    '''
    PENDING = 0
    IN_FLIGHT = 1
    FAILED = 2
    DONE = 10
    DEAD = 11

    TERMINAL_MIN = DONE

REQUEST_STATUS_ACTIVE = (
    RequestStatus.PENDING, RequestStatus.IN_FLIGHT, RequestStatus.FAILED)
REQUEST_STATUS_CLAIMABLE = (RequestStatus.PENDING, RequestStatus.FAILED)