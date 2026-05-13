# -*- coding: utf-8 -*-
# Stub file generated from lymow_pb2.py for editor autocomplete/type hints.
# Runtime implementation is in lymow_pb2.py.

from __future__ import annotations

from typing import Any, Iterable
from google.protobuf import descriptor as _descriptor
from google.protobuf import message as _message
from google.protobuf.internal import containers as _containers

DESCRIPTOR: _descriptor.FileDescriptor

class PbAreaInfo(_message.Message):
    areaOrGlobal: int
    cleanZoneIds: _containers.RepeatedScalarFieldContainer[str]
    def __init__(self, *, areaOrGlobal: int = ..., cleanZoneIds: Iterable[str] | None = ..., **kwargs: Any) -> None: ...

class PbBaseInput(_message.Message):
    def __init__(self, **kwargs: Any) -> None: ...

class PbBdpCmd(_message.Message):
    def __init__(self, **kwargs: Any) -> None: ...

class PbCutZone(_message.Message):
    def __init__(self, **kwargs: Any) -> None: ...

class PbFloor(_message.Message):
    def __init__(self, **kwargs: Any) -> None: ...

class PbGeoFencing(_message.Message):
    def __init__(self, **kwargs: Any) -> None: ...

class PbGpsInfo(_message.Message):
    def __init__(self, **kwargs: Any) -> None: ...

class PbIotCmd(_message.Message):
    def __init__(self, **kwargs: Any) -> None: ...

class PbLcdPinCode(_message.Message):
    def __init__(self, **kwargs: Any) -> None: ...

class PbMergeZone(_message.Message):
    def __init__(self, **kwargs: Any) -> None: ...

class PbPath(_message.Message):
    def __init__(self, **kwargs: Any) -> None: ...

class PbPolygon(_message.Message):
    points: _containers.RepeatedCompositeFieldContainer[PbPoint]
    def __init__(self, *, points: Iterable[PbPoint] | None = ..., **kwargs: Any) -> None: ...

class PbSchedules(_message.Message):
    tasks: _containers.RepeatedCompositeFieldContainer[PbSchedule]
    def __init__(self, *, tasks: Iterable[PbSchedule] | None = ..., **kwargs: Any) -> None: ...

class PbSchedule(_message.Message):
    def __init__(self, **kwargs: Any) -> None: ...

class PbNoGoZone(_message.Message):
    def __init__(self, **kwargs: Any) -> None: ...

class PbZone(_message.Message):
    basicInfo: PbZoneBasicInfo
    zoneConfig: PbZoneConfig
    ppBasicInfo: PbZonePpBasicInfo
    nogoZoneHashIds: _containers.RepeatedScalarFieldContainer[str]
    def __init__(
        self,
        *,
        basicInfo: PbZoneBasicInfo | None = ...,
        zoneConfig: PbZoneConfig | None = ...,
        ppBasicInfo: PbZonePpBasicInfo | None = ...,
        nogoZoneHashIds: Iterable[str] | None = ...,
        **kwargs: Any,
    ) -> None: ...

class queryAck(_message.Message):
    def __init__(self, **kwargs: Any) -> None: ...

class ErrorList(_message.Message):
    code: int
    percent: float
    def __init__(self, *, code: int = ..., percent: float = ..., **kwargs: Any) -> None: ...

class GeoFence(_message.Message):
    name: str
    centerLatitude: float
    centerLongitude: float
    radius: int
    def __init__(self, *, name: str = ..., centerLatitude: float = ..., centerLongitude: float = ..., radius: int = ..., **kwargs: Any) -> None: ...

class PbAlgoLocInput(_message.Message):
    chargingStationLoc: PbPose
    locStatus: int
    localizationInfo: PbLocalizationInfo
    tagDec: int
    robotPose: PbPose3D
    pib: PbPose3D
    cmdOpenCamLed: bool
    enuBasePoint: PbRobotLLACoords
    pti: PbPose3D
    initPose: PbPose
    autonomousScore: float
    locCmd: int
    def __init__(
        self,
        *,
        chargingStationLoc: PbPose | None = ...,
        locStatus: int = ...,
        localizationInfo: PbLocalizationInfo | None = ...,
        tagDec: int = ...,
        robotPose: PbPose3D | None = ...,
        pib: PbPose3D | None = ...,
        cmdOpenCamLed: bool = ...,
        enuBasePoint: PbRobotLLACoords | None = ...,
        pti: PbPose3D | None = ...,
        initPose: PbPose | None = ...,
        autonomousScore: float = ...,
        locCmd: int = ...,
        **kwargs: Any,
    ) -> None: ...

class PbAlgoLocOutput(_message.Message):
    locCmd: int
    locUseTag: int
    updateEnuBasePoint: bool
    sensorConfidence: PbSensorsConfidence
    cuttingHeight: int
    camLedStatus: int
    chargingStationLoc: PbPose
    useGnss: bool
    batStatus: int
    def __init__(
        self,
        *,
        locCmd: int = ...,
        locUseTag: int = ...,
        updateEnuBasePoint: bool = ...,
        sensorConfidence: PbSensorsConfidence | None = ...,
        cuttingHeight: int = ...,
        camLedStatus: int = ...,
        chargingStationLoc: PbPose | None = ...,
        useGnss: bool = ...,
        batStatus: int = ...,
        **kwargs: Any,
    ) -> None: ...

class PbAlgoSegInput(_message.Message):
    segStatus: int
    def __init__(self, *, segStatus: int = ..., **kwargs: Any) -> None: ...

class PbAlgoSegOutput(_message.Message):
    segCmd: int
    def __init__(self, *, segCmd: int = ..., **kwargs: Any) -> None: ...

class PbBaseOutput(_message.Message):
    battery: int
    twist: PbTwist
    cutSpeed: PbCutSpeed
    cutHeight: int
    raiseCutHeight: bool
    lowerCutHeight: bool
    socSignal: int
    lcdPinCode: PbLcdPinCode
    bdpCmd: PbBdpCmd
    factoryTest: PbFactoryTest
    wirelessStatus: PbWirelessStatus
    def __init__(
        self,
        *,
        battery: int = ...,
        twist: PbTwist | None = ...,
        cutSpeed: PbCutSpeed | None = ...,
        cutHeight: int = ...,
        raiseCutHeight: bool = ...,
        lowerCutHeight: bool = ...,
        socSignal: int = ...,
        lcdPinCode: PbLcdPinCode | None = ...,
        bdpCmd: PbBdpCmd | None = ...,
        factoryTest: PbFactoryTest | None = ...,
        wirelessStatus: PbWirelessStatus | None = ...,
        **kwargs: Any,
    ) -> None: ...

class PbBtMap(_message.Message):
    queryIndex: int
    queryAck: queryAck
    queryPath: bool
    queryMap: bool
    def __init__(self, *, queryIndex: int = ..., queryAck: queryAck | None = ..., queryPath: bool = ..., queryMap: bool = ..., **kwargs: Any) -> None: ...

class PbChannel(_message.Message):
    hashId: str
    zone1: str
    zone2: str
    isValid: bool
    polygon: PbPolygon
    isDockingChannel: bool
    updateTime: int
    detectMode: int
    cutHeight: int
    channelLift: bool
    def __init__(
        self,
        *,
        hashId: str = ...,
        zone1: str = ...,
        zone2: str = ...,
        isValid: bool = ...,
        polygon: PbPolygon | None = ...,
        isDockingChannel: bool = ...,
        updateTime: int = ...,
        detectMode: int = ...,
        cutHeight: int = ...,
        channelLift: bool = ...,
        **kwargs: Any,
    ) -> None: ...

class PbChannelConfig(_message.Message):
    detectMode: int
    cutHeight: int
    channelLift: bool
    def __init__(self, *, detectMode: int = ..., cutHeight: int = ..., channelLift: bool = ..., **kwargs: Any) -> None: ...

class PbCleanInfo(_message.Message):
    cleanTime: int
    cleanArea: float
    areaInfo: PbAreaInfo
    remainCleanTime: int
    cleanPercent: float
    mapArea: float
    def __init__(
        self,
        *,
        cleanTime: int = ...,
        cleanArea: float = ...,
        areaInfo: PbAreaInfo | None = ...,
        remainCleanTime: int = ...,
        cleanPercent: float = ...,
        mapArea: float = ...,
        **kwargs: Any,
    ) -> None: ...

class PbCleanReport(_message.Message):
    cleanStartTime: int
    cleanInfo: PbCleanInfo
    mowEndType: int
    errorList: _containers.RepeatedCompositeFieldContainer[PbErrorEntry]
    statusTimes: _containers.RepeatedScalarFieldContainer[int]
    usedBattery: int
    def __init__(
        self,
        *,
        cleanStartTime: int = ...,
        cleanInfo: PbCleanInfo | None = ...,
        mowEndType: int = ...,
        errorList: Iterable[PbErrorEntry] | None = ...,
        statusTimes: Iterable[int] | None = ...,
        usedBattery: int = ...,
        **kwargs: Any,
    ) -> None: ...

class PbErrorEntry(_message.Message):
    code: int
    percent: float
    def __init__(self, *, code: int = ..., percent: float = ..., **kwargs: Any) -> None: ...

class PbCleanSummary(_message.Message):
    totalCleanTime: int
    totalCleanArea: float
    totalCleanTimes: int
    def __init__(self, *, totalCleanTime: int = ..., totalCleanArea: float = ..., totalCleanTimes: int = ..., **kwargs: Any) -> None: ...

class PbCutSpeed(_message.Message):
    left: int
    right: int
    def __init__(self, *, left: int = ..., right: int = ..., **kwargs: Any) -> None: ...

class PbDebugSetting(_message.Message):
    uploadLog: bool
    uploadVersion: bool
    uploadProgress: int
    bagTag: str
    queryWifiConfig: bool
    bagRecording: bool
    downloadProgress: int
    hwClockUpdated: bool
    description: str
    uploadRobotConfig: bool
    uploadTaskConfig: bool
    execCmd: str
    def __init__(
        self,
        *,
        uploadLog: bool = ...,
        uploadVersion: bool = ...,
        uploadProgress: int = ...,
        bagTag: str = ...,
        queryWifiConfig: bool = ...,
        bagRecording: bool = ...,
        downloadProgress: int = ...,
        hwClockUpdated: bool = ...,
        description: str = ...,
        uploadRobotConfig: bool = ...,
        uploadTaskConfig: bool = ...,
        execCmd: str = ...,
        **kwargs: Any,
    ) -> None: ...

class PbDeviceProfile(_message.Message):
    fwVersion: str
    mcuVersion: str
    softwareVersion: str
    wifiSsid: str
    ipAddress: str
    macAddress: str
    sn: str
    rtkSn: str
    simId: str
    wheelVer: str
    knifeVer: str
    def __init__(
        self,
        *,
        fwVersion: str = ...,
        mcuVersion: str = ...,
        softwareVersion: str = ...,
        wifiSsid: str = ...,
        ipAddress: str = ...,
        macAddress: str = ...,
        sn: str = ...,
        rtkSn: str = ...,
        simId: str = ...,
        wheelVer: str = ...,
        knifeVer: str = ...,
        **kwargs: Any,
    ) -> None: ...

class PbFactoryTest(_message.Message):
    cmd: int
    data: str
    errorCode: int
    def __init__(self, *, cmd: int = ..., data: str = ..., errorCode: int = ..., **kwargs: Any) -> None: ...

class PbFloorInfo(_message.Message):
    hashId: str
    name: str
    isSelected: bool
    rtkSn: str
    def __init__(self, *, hashId: str = ..., name: str = ..., isSelected: bool = ..., rtkSn: str = ..., **kwargs: Any) -> None: ...

class PbHashType(_message.Message):
    hashId: str
    hashType: int
    isDelete: bool
    def __init__(self, *, hashId: str = ..., hashType: int = ..., isDelete: bool = ..., **kwargs: Any) -> None: ...

class PbInput(_message.Message):
    msgId: int
    version: int
    userCtrl: int
    baseInput: PbBaseInput
    appConnect: int
    cloudConnect: int
    debugSetting: PbDebugSetting
    remoteControl: PbRemoteControl
    schedule: PbSchedules
    map: PbMap
    robotConfig: PbRobotConfig
    algoLocInput: PbAlgoLocInput
    algoSegInput: PbAlgoSegInput
    audioId: int
    wifiConfig: PbWifiConfig
    btMap: PbBtMap
    theftSetting: PbTheftSetting
    wirelessStatus: PbWirelessStatus
    taskConfig: PbTaskConfig
    uuid: str
    floorData: PbFloor
    startMode: int
    mergeZone: PbMergeZone
    cutZone: PbCutZone
    def __init__(
        self,
        *,
        msgId: int = ...,
        version: int = ...,
        userCtrl: int = ...,
        baseInput: PbBaseInput | None = ...,
        appConnect: int = ...,
        cloudConnect: int = ...,
        debugSetting: PbDebugSetting | None = ...,
        remoteControl: PbRemoteControl | None = ...,
        schedule: PbSchedules | None = ...,
        map: PbMap | None = ...,
        robotConfig: PbRobotConfig | None = ...,
        algoLocInput: PbAlgoLocInput | None = ...,
        algoSegInput: PbAlgoSegInput | None = ...,
        audioId: int = ...,
        wifiConfig: PbWifiConfig | None = ...,
        btMap: PbBtMap | None = ...,
        theftSetting: PbTheftSetting | None = ...,
        wirelessStatus: PbWirelessStatus | None = ...,
        taskConfig: PbTaskConfig | None = ...,
        uuid: str = ...,
        floorData: PbFloor | None = ...,
        startMode: int = ...,
        mergeZone: PbMergeZone | None = ...,
        cutZone: PbCutZone | None = ...,
        **kwargs: Any,
    ) -> None: ...

class PbLiftMotor(_message.Message):
    pos: int
    temperature: int
    current: int
    def __init__(self, *, pos: int = ..., temperature: int = ..., current: int = ..., **kwargs: Any) -> None: ...

class PbLineFollow(_message.Message):
    initK: float
    initB: float
    curDir: float
    curK: float
    curB: float
    nextB: float
    followHand: int
    def __init__(
        self,
        *,
        initK: float = ...,
        initB: float = ...,
        curDir: float = ...,
        curK: float = ...,
        curB: float = ...,
        nextB: float = ...,
        followHand: int = ...,
        **kwargs: Any,
    ) -> None: ...

class PbLocalizationInfo(_message.Message):
    numSatellites: int
    horizontalAccuracy: float
    verticalAccuracy: float
    positionQuality: int
    locNodeStatus: int
    gpsInfo: PbGpsInfo
    def __init__(
        self,
        *,
        numSatellites: int = ...,
        horizontalAccuracy: float = ...,
        verticalAccuracy: float = ...,
        positionQuality: int = ...,
        locNodeStatus: int = ...,
        gpsInfo: PbGpsInfo | None = ...,
        **kwargs: Any,
    ) -> None: ...

class PbMap(_message.Message):
    goZones: _containers.RepeatedCompositeFieldContainer[PbZone]
    nogoZones: _containers.RepeatedCompositeFieldContainer[PbNoGoZone]
    channels: _containers.RepeatedCompositeFieldContainer[PbChannel]
    chargingStationLoc: PbPose
    isIncomplete: bool
    diagonalCoords: _containers.RepeatedCompositeFieldContainer[PbPoint]
    enuBasePoint: PbRobotLLACoords
    taskConfig: PbTaskConfig
    modifyHashs: _containers.RepeatedCompositeFieldContainer[PbHashType]
    floorInfo: PbFloorInfo
    globalZoneConfig: PbZoneConfig
    globalChannelConfig: PbChannelConfig
    runTimeConfig: PbRunTimeConfig
    def __init__(
        self,
        *,
        goZones: Iterable[PbZone] | None = ...,
        nogoZones: Iterable[PbNoGoZone] | None = ...,
        channels: Iterable[PbChannel] | None = ...,
        chargingStationLoc: PbPose | None = ...,
        isIncomplete: bool = ...,
        diagonalCoords: Iterable[PbPoint] | None = ...,
        enuBasePoint: PbRobotLLACoords | None = ...,
        taskConfig: PbTaskConfig | None = ...,
        modifyHashs: Iterable[PbHashType] | None = ...,
        floorInfo: PbFloorInfo | None = ...,
        globalZoneConfig: PbZoneConfig | None = ...,
        globalChannelConfig: PbChannelConfig | None = ...,
        runTimeConfig: PbRunTimeConfig | None = ...,
        **kwargs: Any,
    ) -> None: ...

class PbMatrix(_message.Message):
    cleanMatrix: str
    row: int
    col: int
    def __init__(self, *, cleanMatrix: str = ..., row: int = ..., col: int = ..., **kwargs: Any) -> None: ...

class PbMotor(_message.Message):
    speed: int
    temperature: int
    current: int
    def __init__(self, *, speed: int = ..., temperature: int = ..., current: int = ..., **kwargs: Any) -> None: ...

class PbMutateResult(_message.Message):
    code: int
    errorMsg: str
    def __init__(self, *, code: int = ..., errorMsg: str = ..., **kwargs: Any) -> None: ...

class PbNetDetailInfo(_message.Message):
    currentNet: int
    wifiName: str
    wifiIp: str
    wifiSignal: int
    simCardStatus: int
    simIp: str
    simSignal: int
    simRegistration: int
    simConnection: bool
    simIccid: str
    def __init__(
        self,
        *,
        currentNet: int = ...,
        wifiName: str = ...,
        wifiIp: str = ...,
        wifiSignal: int = ...,
        simCardStatus: int = ...,
        simIp: str = ...,
        simSignal: int = ...,
        simRegistration: int = ...,
        simConnection: bool = ...,
        simIccid: str = ...,
        **kwargs: Any,
    ) -> None: ...

class PbOutput(_message.Message):
    msgId: int
    version: int
    errorCodes: _containers.RepeatedScalarFieldContainer[int]
    warningCodes: _containers.RepeatedScalarFieldContainer[int]
    robotInfo: PbRobotInfo
    localizationInfo: PbLocalizationInfo
    baseOutput: PbBaseOutput
    iotCmd: PbIotCmd
    debugSetting: PbDebugSetting
    deviceInfo: PbDeviceProfile
    map: PbMap
    cleanInfo: PbCleanInfo
    path: PbPath
    pose: PbPose
    promptInfo: PbPromptInfo
    schedule: PbSchedules
    robotConfig: PbRobotConfig
    outputCtrl: int
    algoLocOutput: PbAlgoLocOutput
    algoSegOutput: PbAlgoSegOutput
    audioId: int
    wifiConfigRes: PbWifiConfigResponse
    btMap: PbBtMap
    chargingStationLoc: PbPose
    mobilePushNotification: int
    robotLlaCoords: PbRobotLLACoords
    theftLock: bool
    cleanReport: PbCleanReport
    robotPosePib: PbPoint
    taskConfig: PbTaskConfig
    floorData: PbFloor
    netDetailInfo: PbNetDetailInfo
    rtkDiagnosticL1: PbRtkDiagnosticL1
    rtkDiagnosticL2: PbRtkDiagnosticL2
    def __init__(
        self,
        *,
        msgId: int = ...,
        version: int = ...,
        errorCodes: Iterable[int] | None = ...,
        warningCodes: Iterable[int] | None = ...,
        robotInfo: PbRobotInfo | None = ...,
        localizationInfo: PbLocalizationInfo | None = ...,
        baseOutput: PbBaseOutput | None = ...,
        iotCmd: PbIotCmd | None = ...,
        debugSetting: PbDebugSetting | None = ...,
        deviceInfo: PbDeviceProfile | None = ...,
        map: PbMap | None = ...,
        cleanInfo: PbCleanInfo | None = ...,
        path: PbPath | None = ...,
        pose: PbPose | None = ...,
        promptInfo: PbPromptInfo | None = ...,
        schedule: PbSchedules | None = ...,
        robotConfig: PbRobotConfig | None = ...,
        outputCtrl: int = ...,
        algoLocOutput: PbAlgoLocOutput | None = ...,
        algoSegOutput: PbAlgoSegOutput | None = ...,
        audioId: int = ...,
        wifiConfigRes: PbWifiConfigResponse | None = ...,
        btMap: PbBtMap | None = ...,
        chargingStationLoc: PbPose | None = ...,
        mobilePushNotification: int = ...,
        robotLlaCoords: PbRobotLLACoords | None = ...,
        theftLock: bool = ...,
        cleanReport: PbCleanReport | None = ...,
        robotPosePib: PbPoint | None = ...,
        taskConfig: PbTaskConfig | None = ...,
        floorData: PbFloor | None = ...,
        netDetailInfo: PbNetDetailInfo | None = ...,
        rtkDiagnosticL1: PbRtkDiagnosticL1 | None = ...,
        rtkDiagnosticL2: PbRtkDiagnosticL2 | None = ...,
        **kwargs: Any,
    ) -> None: ...

class PbPoint(_message.Message):
    x: float
    y: float
    def __init__(self, *, x: float = ..., y: float = ..., **kwargs: Any) -> None: ...

class PbPose(_message.Message):
    x: float
    y: float
    theta: float
    z: float
    def __init__(self, *, x: float = ..., y: float = ..., theta: float = ..., z: float = ..., **kwargs: Any) -> None: ...

class PbPose3D(_message.Message):
    pX: float
    pY: float
    pZ: float
    qX: float
    qY: float
    qZ: float
    qW: float
    def __init__(self, *, pX: float = ..., pY: float = ..., pZ: float = ..., qX: float = ..., qY: float = ..., qZ: float = ..., qW: float = ..., **kwargs: Any) -> None: ...

class PbPromptInfo(_message.Message):
    selfCheckingRet: PbSelfCheckingResult
    zoneRet: PbZoneSetResult
    mutateRet: PbMutateResult
    def __init__(
        self,
        *,
        selfCheckingRet: PbSelfCheckingResult | None = ...,
        zoneRet: PbZoneSetResult | None = ...,
        mutateRet: PbMutateResult | None = ...,
        **kwargs: Any,
    ) -> None: ...

class PbRRConfig(_message.Message):
    enableRr: bool
    resumePeriodStart: PbTimeZone
    resumePeriodEnd: PbTimeZone
    rechargeBat: int
    resumeBat: int
    def __init__(
        self,
        *,
        enableRr: bool = ...,
        resumePeriodStart: PbTimeZone | None = ...,
        resumePeriodEnd: PbTimeZone | None = ...,
        rechargeBat: int = ...,
        resumeBat: int = ...,
        **kwargs: Any,
    ) -> None: ...

class PbRebootResume(_message.Message):
    taskFinished_: bool
    totalRemainingArea_: float
    totalTaskArea_: float
    boustrophedonStarted_: bool
    localWinFinetuneIndex_: int
    needClearAllObs_: bool
    chessCleaning_: bool
    chessBoard_: bool
    edgePath_: int
    wallFollowingKeepCnt_: int
    rechargeResume_: bool
    isZoneOrderDetermined_: bool
    wallStartIndex: int
    lastIndexFromStart_: int
    curLapNums_: int
    perimeterLaps_: int
    isWallFollowingCompleted_: bool
    isWallCleaning_: bool
    wallCcw_: int
    resumeMode: int
    isResumeChannel_: bool
    curPose_: PbPose
    curZoneId_: str
    lineFollow_: PbLineFollow
    cleaningYPlus: int
    initPose_: PbPose
    cleanMatrix: PbMatrix
    uncleanMatrix: PbMatrix
    anti_: int
    curLocalIndex_: int
    startMode: int
    usedBattery: int
    cleanStartTime: int
    def __init__(
        self,
        *,
        taskFinished_: bool = ...,
        totalRemainingArea_: float = ...,
        totalTaskArea_: float = ...,
        boustrophedonStarted_: bool = ...,
        localWinFinetuneIndex_: int = ...,
        needClearAllObs_: bool = ...,
        chessCleaning_: bool = ...,
        chessBoard_: bool = ...,
        edgePath_: int = ...,
        wallFollowingKeepCnt_: int = ...,
        rechargeResume_: bool = ...,
        isZoneOrderDetermined_: bool = ...,
        wallStartIndex: int = ...,
        lastIndexFromStart_: int = ...,
        curLapNums_: int = ...,
        perimeterLaps_: int = ...,
        isWallFollowingCompleted_: bool = ...,
        isWallCleaning_: bool = ...,
        wallCcw_: int = ...,
        resumeMode: int = ...,
        isResumeChannel_: bool = ...,
        curPose_: PbPose | None = ...,
        curZoneId_: str = ...,
        lineFollow_: PbLineFollow | None = ...,
        cleaningYPlus: int = ...,
        initPose_: PbPose | None = ...,
        cleanMatrix: PbMatrix | None = ...,
        uncleanMatrix: PbMatrix | None = ...,
        anti_: int = ...,
        curLocalIndex_: int = ...,
        startMode: int = ...,
        usedBattery: int = ...,
        cleanStartTime: int = ...,
        **kwargs: Any,
    ) -> None: ...

class PbRemoteControl(_message.Message):
    linearSpeed: float
    angularSpeed: float
    def __init__(self, *, linearSpeed: float = ..., angularSpeed: float = ..., **kwargs: Any) -> None: ...

class PbRobotConfig(_message.Message):
    rcCutSpeed: int
    rcCutHeight: int
    rcRaiseCutHeight: bool
    rcLowerCutHeight: bool
    audioVolume: int
    isOpenLed: bool
    signal: int
    lcdPinCode: PbLcdPinCode
    cmdCellularSwitch: bool
    metric_4g: bool
    camLedStatus: int
    vehLedStatus: int
    openLedTime: PbTimeZone
    closeLedTime: PbTimeZone
    resumeBat: int
    rtkBinding: PbRtkBinding
    rrConfig: PbRRConfig
    scheduleId: int
    schedulePathOffset: int
    timezoneOffset: int
    dockOnError: bool
    def __init__(
        self,
        *,
        rcCutSpeed: int = ...,
        rcCutHeight: int = ...,
        rcRaiseCutHeight: bool = ...,
        rcLowerCutHeight: bool = ...,
        audioVolume: int = ...,
        isOpenLed: bool = ...,
        signal: int = ...,
        lcdPinCode: PbLcdPinCode | None = ...,
        cmdCellularSwitch: bool = ...,
        metric_4g: bool = ...,
        camLedStatus: int = ...,
        vehLedStatus: int = ...,
        openLedTime: PbTimeZone | None = ...,
        closeLedTime: PbTimeZone | None = ...,
        resumeBat: int = ...,
        rtkBinding: PbRtkBinding | None = ...,
        rrConfig: PbRRConfig | None = ...,
        scheduleId: int = ...,
        schedulePathOffset: int = ...,
        timezoneOffset: int = ...,
        dockOnError: bool = ...,
        **kwargs: Any,
    ) -> None: ...

class PbRobotInfo(_message.Message):
    robotStatus: int
    battery: int
    wifiSignalQuality: int
    lteSignalQuality: int
    btSignalQuality: int
    workStatus: int
    isRecharging: bool
    isCharging: bool
    wifiWorking: bool
    lteWorking: bool
    def __init__(
        self,
        *,
        robotStatus: int = ...,
        battery: int = ...,
        wifiSignalQuality: int = ...,
        lteSignalQuality: int = ...,
        btSignalQuality: int = ...,
        workStatus: int = ...,
        isRecharging: bool = ...,
        isCharging: bool = ...,
        wifiWorking: bool = ...,
        lteWorking: bool = ...,
        **kwargs: Any,
    ) -> None: ...

class PbRobotLLACoords(_message.Message):
    latitude: float
    longitude: float
    altitude: float
    def __init__(self, *, latitude: float = ..., longitude: float = ..., altitude: float = ..., **kwargs: Any) -> None: ...

class PbRtkBinding(_message.Message):
    rtkLocid: str
    powerMode: str
    def __init__(self, *, rtkLocid: str = ..., powerMode: str = ..., **kwargs: Any) -> None: ...

class PbRtkDiagnosticL1(_message.Message):
    rtkStatus: int
    precision: float
    satelliteCount: int
    l1SatelliteCount: int
    l2SatelliteCount: int
    l5SatelliteCount: int
    l1Snr: int
    l2Snr: int
    l5Snr: int
    baseStationStatus: int
    baseDataErrorRate: float
    def __init__(
        self,
        *,
        rtkStatus: int = ...,
        precision: float = ...,
        satelliteCount: int = ...,
        l1SatelliteCount: int = ...,
        l2SatelliteCount: int = ...,
        l5SatelliteCount: int = ...,
        l1Snr: int = ...,
        l2Snr: int = ...,
        l5Snr: int = ...,
        baseStationStatus: int = ...,
        baseDataErrorRate: float = ...,
        **kwargs: Any,
    ) -> None: ...

class PbRtkDiagnosticL2(_message.Message):
    diffAge: float
    loraBps0: int
    loraBps1: int
    loraBps2: int
    hwDc0: float
    hwDc1: float
    hwDc2: float
    cwRatio0: int
    cwRatio1: int
    cwRatio2: int
    antValue0: int
    antValue1: int
    antValue2: int
    def __init__(
        self,
        *,
        diffAge: float = ...,
        loraBps0: int = ...,
        loraBps1: int = ...,
        loraBps2: int = ...,
        hwDc0: float = ...,
        hwDc1: float = ...,
        hwDc2: float = ...,
        cwRatio0: int = ...,
        cwRatio1: int = ...,
        cwRatio2: int = ...,
        antValue0: int = ...,
        antValue1: int = ...,
        antValue2: int = ...,
        **kwargs: Any,
    ) -> None: ...

class PbRunTimeConfig(_message.Message):
    cutHeight: int
    moveSpeed: float
    cutSpeed: int
    channelConfig: PbChannelConfig
    def __init__(self, *, cutHeight: int = ..., moveSpeed: float = ..., cutSpeed: int = ..., channelConfig: PbChannelConfig | None = ..., **kwargs: Any) -> None: ...

class PbScheduleConfig(_message.Message):
    hashId: str
    cutHeight: int
    moveSpeed: float
    cleanDir: int
    def __init__(self, *, hashId: str = ..., cutHeight: int = ..., moveSpeed: float = ..., cleanDir: int = ..., **kwargs: Any) -> None: ...

class PbSelfCheckingResult(_message.Message):
    batteryPass: bool
    rtkPass: bool
    cliffPass: bool
    bladePass: bool
    rainPass: bool
    algoPass: bool
    def __init__(
        self,
        *,
        batteryPass: bool = ...,
        rtkPass: bool = ...,
        cliffPass: bool = ...,
        bladePass: bool = ...,
        rainPass: bool = ...,
        algoPass: bool = ...,
        **kwargs: Any,
    ) -> None: ...

class PbSensorsConfidence(_message.Message):
    camera1Conf: int
    camera2Conf: int
    gnssConf: int
    def __init__(self, *, camera1Conf: int = ..., camera2Conf: int = ..., gnssConf: int = ..., **kwargs: Any) -> None: ...

class PbTaskConfig(_message.Message):
    chargingMode: int
    zoneOrder: int
    rainCleaning: bool
    disableChargingPark: bool
    def __init__(self, *, chargingMode: int = ..., zoneOrder: int = ..., rainCleaning: bool = ..., disableChargingPark: bool = ..., **kwargs: Any) -> None: ...

class PbTheftSetting(_message.Message):
    geoFencing: PbGeoFencing
    theftDetectionSwitch: bool
    appLock: bool
    def __init__(self, *, geoFencing: PbGeoFencing | None = ..., theftDetectionSwitch: bool = ..., appLock: bool = ..., **kwargs: Any) -> None: ...

class PbTimeZone(_message.Message):
    hour: int
    minute: int
    def __init__(self, *, hour: int = ..., minute: int = ..., **kwargs: Any) -> None: ...

class PbTwist(_message.Message):
    linear: float
    angular: float
    def __init__(self, *, linear: float = ..., angular: float = ..., **kwargs: Any) -> None: ...

class PbUserBinding(_message.Message):
    userId: str
    userRegion: str
    identityId: str
    utcTime: str
    def __init__(self, *, userId: str = ..., userRegion: str = ..., identityId: str = ..., utcTime: str = ..., **kwargs: Any) -> None: ...

class PbUserBindingResponse(_message.Message):
    deviceSn: str
    deviceBt: str
    def __init__(self, *, deviceSn: str = ..., deviceBt: str = ..., **kwargs: Any) -> None: ...

class PbWifiConfig(_message.Message):
    ssid: str
    password: str
    queryWifiList: bool
    userBinding: PbUserBinding
    secret: int
    def __init__(self, *, ssid: str = ..., password: str = ..., queryWifiList: bool = ..., userBinding: PbUserBinding | None = ..., secret: int = ..., **kwargs: Any) -> None: ...

class PbWifiConfigResponse(_message.Message):
    status: str
    ip: str
    port: str
    error: str
    wifiRssi: str
    userBindingRes: PbUserBindingResponse
    def __init__(
        self,
        *,
        status: str = ...,
        ip: str = ...,
        port: str = ...,
        error: str = ...,
        wifiRssi: str = ...,
        userBindingRes: PbUserBindingResponse | None = ...,
        **kwargs: Any,
    ) -> None: ...

class PbWifiListItem(_message.Message):
    ssid: str
    rssi: str
    needSecret: int
    def __init__(self, *, ssid: str = ..., rssi: str = ..., needSecret: int = ..., **kwargs: Any) -> None: ...

class PbWirelessStatus(_message.Message):
    btStatus: int
    wifiStatus: int
    cellularStatus: int
    def __init__(self, *, btStatus: int = ..., wifiStatus: int = ..., cellularStatus: int = ..., **kwargs: Any) -> None: ...

class PbZoneBasicInfo(_message.Message):
    type: int
    name: str
    hashId: str
    isEnabled: bool
    polygon: PbPolygon
    zoneRename: str
    updateTime: int
    mowOrder: int
    mowOrderTextPos: PbPoint
    def __init__(
        self,
        *,
        type: int = ...,
        name: str = ...,
        hashId: str = ...,
        isEnabled: bool = ...,
        polygon: PbPolygon | None = ...,
        zoneRename: str = ...,
        updateTime: int = ...,
        mowOrder: int = ...,
        mowOrderTextPos: PbPoint | None = ...,
        **kwargs: Any,
    ) -> None: ...

class PbZoneConfig(_message.Message):
    cutHeight: int
    raiseCutHeight: bool
    lowerCutHeight: bool
    moveSpeed: float
    brushSpeed: int
    cutSpeed: int
    cleanMode: int
    cleanDir: int
    pathSpacing: int
    perimeterMowLaps: int
    perimeterMowDir: int
    noGoMowLaps: int
    obsDecMode: int
    pathOrder: bool
    startProgress: int
    relativeCleanDir: int
    lineFollowMode: bool
    disableOuterDischarge: bool
    followDetectMode: int
    def __init__(
        self,
        *,
        cutHeight: int = ...,
        raiseCutHeight: bool = ...,
        lowerCutHeight: bool = ...,
        moveSpeed: float = ...,
        brushSpeed: int = ...,
        cutSpeed: int = ...,
        cleanMode: int = ...,
        cleanDir: int = ...,
        pathSpacing: int = ...,
        perimeterMowLaps: int = ...,
        perimeterMowDir: int = ...,
        noGoMowLaps: int = ...,
        obsDecMode: int = ...,
        pathOrder: bool = ...,
        startProgress: int = ...,
        relativeCleanDir: int = ...,
        lineFollowMode: bool = ...,
        disableOuterDischarge: bool = ...,
        followDetectMode: int = ...,
        **kwargs: Any,
    ) -> None: ...

class PbZonePpBasicInfo(_message.Message):
    bound_00: PbPoint
    bound_11: PbPoint
    area: int
    isClockwise: bool
    innerPoint: PbPoint
    obsMap: bytes
    def __init__(
        self,
        *,
        bound_00: PbPoint | None = ...,
        bound_11: PbPoint | None = ...,
        area: int = ...,
        isClockwise: bool = ...,
        innerPoint: PbPoint | None = ...,
        obsMap: bytes = ...,
        **kwargs: Any,
    ) -> None: ...

class PbZoneSetResult(_message.Message):
    code: int
    hashId: str
    def __init__(self, *, code: int = ..., hashId: str = ..., **kwargs: Any) -> None: ...
