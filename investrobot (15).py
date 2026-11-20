//@version=6
// =====================================================================================================================
//  SMC Pro [improved] — переработанная логика Smart Money Concepts
//  Оригинальная идея и визуальный язык: "Smart Money Concepts [LuxAlgo]" (CC BY-NC-SA 4.0)
//  Эта версия распространяется под той же лицензией CC BY-NC-SA 4.0.
//
//  ЧТО ИСПРАВЛЕНО ОТНОСИТЕЛЬНО ОРИГИНАЛА:
//   1) Свинги: ta.pivothigh/pivotlow (симметричные legs слева И справа) вместо "high[size] > ta.highest(size)"
//      -> в разметку больше не попадают нижние максимумы в даунтренде (главный источник ложных BOS).
//   2) Структура считается только на закрытом баре (barstate.isconfirmed) + фильтр минимального смещения
//      в ATR -> BOS/CHoCH не "мигают" на реалтайме, история == реалтайм.
//   3) Order Block = последний противоположный бар перед импульсом (а не экстремум окна),
//      с дедупликацией перекрывающихся зон и корректным жизненным циклом бокса
//      (бокс удаляется вместе с зоной -> нет "призрачных" OB).
//   4) FVG: 3-барный гэп на закрытом баре, порог по ATR, без дублей (timeframe.change был на каждом тике),
//      без lookahead-утечки, митигация 50% / полная.
//   5) EQH/EQL: кластер по свингам структуры (а не по микро-пивотам длины 3) + подсветка снятия уровня.
//   6) Premium / Equilibrium / Discount от текущего dealing range (последние свинг H/L), а не от "бегущего" max/min.
//   7) Удаление из массивов — обратным циклом (for ... in с remove() пропускал элементы).
//   8) HTF-фильтр направления: request.security с [1] + lookahead_on (единственный нерепейнтящий паттерн).
//   9) Алерты через alert() с текстом (тип сигнала + цена) + alertcondition для совместимости.
//  10) Цвет свечей считается ПОСЛЕ структуры (в оригинале отставал на 1 бар).
//  11) Ключевые уровни старшего ТФ (PDH/PDL, PWH/PWL, свинги 1H/4H) — магниты, которых на 15m не видно.
//  12) Дашборд в углу графика: структура, HTF, положение в диапазоне, ближайшие зоны (ATR + A+),
//      ближайший ключевой уровень, статистика отскоков A+ зон.
//  13) Алерты «подход к A+ зоне» и «зона сломана» (с паузой между срабатываниями) + alertcondition.
//  14) Пресеты: Интрадей 15m / Свинг 1H / Только A+ / Чистый график — один переключатель.
//  15) Честная статистика A+ зон по сторонам: касание -> отскок на N ATR = успех, пробой = провал,
//      простой дольше N баров = истекло (ничего не теряется: успехи/провалы/истёкшие/в работе).
//  17) POC / профиль объёма: гистограмма объёма у ЛЕВОГО края, линии POC / VAH / VAL и POC прошлого
//      периода (магниты цены), подписи — слева, чтобы не мешать подписям EMA справа.
//  18) Конфлюенс 6 условий (FVG, EMA, дисконт/премиум, POC/Value Area, ключевой уровень, структура);
//      порог задаётся в % от числа доступных условий — и для A+ зон, и для меток BUY/SELL.
//  16) Метки BUY / SELL в момент входа цены в A+ зону; показываются только если статистика этой
//      стороны >= порога и выборка набрана (можно выключить и смотреть все метки).
//
//  ВАЖНО: код не проверялся компилятором TradingView в песочнице. При первом запуске возможны
//         мелкие правки синтаксиса; логика при этом не меняется.
// =====================================================================================================================
indicator('SMC Pro [improved]', 'SMC Pro', overlay = true, max_labels_count = 500, max_lines_count = 500, max_boxes_count = 500)

// ---------------------------------------------------------------------------------------------------------------------
// INPUTS
// ---------------------------------------------------------------------------------------------------------------------
string G_STR = 'Структура'
string G_OB  = 'Order Blocks'
string G_FVG = 'Fair Value Gaps'
string G_EQ  = 'EQH / EQL'
string G_PD  = 'Premium / Discount'
string G_HTF = 'HTF-фильтр'
string G_AL  = 'Алерты'
string G_COL = 'Цвета'
string G_VIEW = 'Вид / чистота графика'
string G_EMA  = 'EMA с других ТФ'
string G_APL  = 'A+ зоны (конфлюенс)'
string G_LVL  = 'Ключевые уровни старшего ТФ'
string G_PRE  = 'Пресеты'
string G_DASH = 'Дашборд и статистика'
string G_SIG  = 'Сигналы BUY / SELL (пункт 7)'
string G_POC  = 'POC (профиль объёма)'

int    iSwingLegs  = input.int(5,     'Swing: баров слева/справа',   minval = 1, maxval = 50, group = G_STR)
int    iIntLegs    = input.int(3,     'Internal: баров слева/справа', minval = 1, maxval = 20, group = G_STR)
bool   iShowSwing  = input.bool(true, 'Swing-структура',              group = G_STR)
bool   iShowInt    = input.bool(false,'Internal-структура',           group = G_STR)
bool   iSwings     = input.bool(false,'Метки HH / HL / LH / LL',      group = G_STR)
bool   iColorCandles = input.bool(false,'Раскрашивать свечи по тренду', group = G_STR)
bool   iWickBreak  = input.bool(false,'Пробой по фитилю (иначе по close)', group = G_STR)
float  iDispMult   = input.float(0.10,'Мин. смещение пробоя, ATR',    minval = 0, step = 0.05, group = G_STR)
bool   iConfirmed  = input.bool(true, 'Только закрытые бары (антирепейнт)', group = G_STR)

// --- чистота графика ---
int    iKeepStruct     = input.int(2,    'Держать последних структур (на направление)', minval = 1, maxval = 10, group = G_VIEW, tooltip = 'Сколько последних линий BOS/CHoCH остаётся на графике. Остальные удаляются автоматически.')
bool   iShowStructLbl  = input.bool(true,'Подписи BOS / CHoCH',        group = G_VIEW)
bool   iExtendLines    = input.bool(false,'Линии во весь график',      group = G_VIEW, tooltip = 'Выкл = короткий отрезок на уровне пробоя (чище). Вкл = линия тянется вправо до текущего бара.')
int    iMaxEQ          = input.int(2,    'Макс. линий EQH / EQL',      minval = 1, maxval = 10, group = G_VIEW)
bool   iKeepMitigated  = input.bool(false,'Оставлять отработанные зоны (бледными)', group = G_VIEW, tooltip = 'Отработанная зона не удаляется, а становится серой пунктирной — видно историю уровней поддержки/сопротивления. Счётчик «создано/снято» в дашборде показывает, сколько зон было на самом деле.')
bool   iHideFar        = input.bool(false, 'Скрывать зоны далеко от цены', group = G_VIEW, tooltip = 'ПО УМОЛЧАНИЮ ВЫКЛЮЧЕНО: все зоны видны всегда. Если включить — зоны дальше порога по ATR прячутся и проявляются, когда цена подходит.')
int    iKeepNear       = input.int(3,     'Всегда видны N ближайших зон', minval = 1, maxval = 10, group = G_VIEW, tooltip = 'Работает только при включённом скрытии далёких зон: столько ближайших поддержек и сопротивлений не прячутся никогда.')
float  iZoneAtr        = input.float(10.0,'Порог «далеко», ATR',           minval = 0.5, maxval = 50, step = 0.5, group = G_VIEW)
bool   iShowEQLbl      = input.bool(true,'Подписи EQH / EQL',          group = G_VIEW)

bool   iShowOB     = input.bool(true,  'Swing OB',                    group = G_OB)
bool   iShowIntOB  = input.bool(true,  'Internal OB',                 group = G_OB, tooltip = 'В оригинале LuxAlgo включены именно внутренние OB — их на графике больше всего. Выключите, если нужны только свинговые зоны.')
int    iMaxOB      = input.int(8,      'Активных зон на структуру',    minval = 1, maxval = 30, group = G_OB)
bool   iOBOnPivot  = input.bool(true,  'Зона и при подтверждении свинга',  group = G_OB, tooltip = 'Создавать OB не только на BOS/CHoCH, но и на подтверждённом свинге — иначе в трендовых участках зоны почти не появляются.')
bool   iAplus      = input.bool(true,  'Выделять A+ зоны',            group = G_APL, tooltip = 'Зона подсвечивается, если у неё есть подтверждения (конфлюенс). Это не гарантия отскока, а фильтр качества.')
int    iAplusPct   = input.int(60,     'Мин. конфлюенс, % от возможного', minval = 30, maxval = 100, group = G_APL, tooltip = 'Условий всего 6: рядом FVG · рядом EMA · правильная половина диапазона · POC или Value Area · ключевой уровень старшего ТФ · структура не против. 70% ≈ 4–5 из 6; 100% = только зоны, где совпало всё доступное.')
float  iAplusPocAtr= input.float(0.4,  'Допуск до POC, ATR',           minval = 0.05, maxval = 3, step = 0.05, group = G_APL)
float  iAplusLevAtr= input.float(0.4,  'Допуск до ключевого уровня, ATR', minval = 0.05, maxval = 3, step = 0.05, group = G_APL)
float  iAplusEmaAtr= input.float(0.5,  'Допуск до EMA старшего ТФ, ATR', minval = 0.1, step = 0.1, group = G_APL)
color  cStrong     = input.color(#ffd400,'Цвет A+ зоны',              group = G_APL)
bool   iAplusOnly  = input.bool(false,'Показывать ТОЛЬКО A+ зоны',     group = G_APL, tooltip = 'Вкл — на графике остаются только зоны с конфлюенсом >= порога (места, где отскок вероятнее). Выкл — все рабочие зоны, A+ выделены золотым.')
string iMitMode    = input.string('Close','Когда OB считается отработанным', options = ['Close', 'Wick', '50%'], group = G_OB, tooltip = 'Close — зона живёт, пока цена не закроется за её дальней границей (поддержка видна до реального пробоя). Wick — удалять при проколе фитилём. 50% — удалять при касании середины зоны (как в оригинале, зоны исчезают очень быстро).')
float  iMinOBAtr   = input.float(0.15,'Мин. высота зоны, ATR',        minval = 0, step = 0.05, group = G_OB)
bool   iObDedup     = input.bool(true, 'Не дублировать зоны (перекрытие > 50%)', group = G_OB, tooltip = 'Вкл: если новая зона почти совпадает с уже существующей, она не создаётся — график чище. Выкл: как в оригинале LuxAlgo — на каждом пробое создаётся новый прямоугольник, они накладываются друг на друга.')
bool   iObSkipBroken= input.bool(true, 'Отбрасывать зоны, пробитые до подтверждения', group = G_OB, tooltip = 'Зона создаётся задним числом (пивот подтверждается позже). Вкл: если цена уже закрылась за её границей до этого момента, зона не рисуется — не появляется «мёртвых» прямоугольников. Выкл: как в оригинале.')

bool   iShowFVG    = input.bool(true,  'Показывать FVG',              group = G_FVG)
float  iFvgMinAtr  = input.float(0.20,'Мин. размер гэпа, ATR',        minval = 0, step = 0.05, group = G_FVG)
string iFvgMit     = input.string('Full', 'Когда FVG считается закрытым', options = ['Full', '50%'], group = G_FVG, tooltip = 'Full — гэп остаётся, пока его не закроют полностью (виден как рабочая зона). 50% — удалять при касании середины.')
int    iMaxFvg     = input.int(8,      'Активных FVG',                 minval = 1, maxval = 40, group = G_FVG)

bool   iShowEQ     = input.bool(true,  'Показывать EQH / EQL',        group = G_EQ)
float  iEqTolAtr   = input.float(0.15,'Допуск равенства, ATR',        minval = 0, step = 0.05, group = G_EQ)
int    iEqScan     = input.int(10,     'Пивотов для сверки',          minval = 2, maxval = 30, group = G_EQ)

bool   iShowPD     = input.bool(false, 'Premium / Discount зоны',     group = G_PD)

string iHtfTf      = input.timeframe('', 'HTF для фильтра (пусто = выкл)', group = G_HTF)
int    iHtfLen     = input.int(50,        'HTF EMA',                  minval = 1, group = G_HTF)
bool   iHtfFilter  = input.bool(false,    'Фильтровать алерты по HTF (зоны не фильтруются)', group = G_HTF, tooltip = 'Влияет только на алерты. Зоны OB/FVG рисуются всегда — иначе в тренде против HTF поддержки/сопротивления просто исчезают.')

bool   iLevOn    = input.bool(true,  'Показывать уровни',            group = G_LVL, tooltip = 'Горизонтальные линии-магниты: экстремумы вчерашнего дня и прошлой недели + последние подтверждённые свинги старших ТФ.')
bool   iLevPd    = input.bool(true,  'PDH / PDL (вчерашние H/L)',    group = G_LVL)
bool   iLevPw    = input.bool(true,  'PWH / PWL (недельные H/L)',    group = G_LVL)
bool   iLevSw    = input.bool(true,  'Свинги 1H / 4H',               group = G_LVL)
string iLevTf1   = input.timeframe('60',  'ТФ свинга 1',             group = G_LVL)
string iLevTf2   = input.timeframe('240', 'ТФ свинга 2',             group = G_LVL)
int    iLevLegs  = input.int(5, 'Длина свинга (слева и справа)', minval = 1, maxval = 50, group = G_LVL, tooltip = 'Сколько баров старшего ТФ должно быть по обе стороны от экстремума, чтобы он считался свингом.')
bool   iLevLbl   = input.bool(true,  'Подписи уровней',              group = G_LVL)

bool   iPocOn      = input.bool(true,  'Показывать POC (профиль объёма)', group = G_POC, tooltip = 'POC — цена, на которой за период наторговано больше всего объёма. Магнит для цены и хороший ориентир «где рынок согласен». Строится приближённо: объём графика раскладывается по ценовым бинам.')
string iPocTf      = input.timeframe('D', 'Период профиля (сброс)',     group = G_POC, tooltip = 'Гистограмма обнуляется при смене этого периода. D = POC текущего дня, W = текущей недели.')
float  iPocStepAtr = input.float(0.2,  'Шаг цены, ATR',               minval = 0.02, maxval = 2, step = 0.02, group = G_POC, tooltip = 'Размер ценового бина. Меньше = точнее POC, но крупнее гистограмма.')
float  iPocVa      = input.float(70,   'Value Area, %',               minval = 50, maxval = 95, group = G_POC)
bool   iPocVaOn    = input.bool(true,  'Показывать VAH / VAL',        group = G_POC, tooltip = 'Границы зоны, где наторговано Value Area % объёма.')
bool   iPocPrevOn  = input.bool(true,  'POC прошлого периода',        group = G_POC, tooltip = 'POC вчерашнего дня — магнит и уровень реакции.')
color  iPocCol     = input.color(#ffd400, 'Цвет POC',                 group = G_POC)
color  iPocVaCol   = input.color(#787b86, 'Цвет VAH / VAL',           group = G_POC)
color  iPocPrevCol = input.color(#b2b5be, 'Цвет POC прошлого периода', group = G_POC)
int    iPocMaxBins  = input.int(120,   'Макс. бинов в профиле', minval = 40, maxval = 400, group = G_POC, tooltip = 'Если цена выходит за сетку, шаг удваивается и соседние бины складываются — объём не теряется и POC не «уезжает» на край профиля.')
bool   iPocProf     = input.bool(true, 'Профиль объёма слева (гистограмма)', group = G_POC)
bool   iPocRangeOn  = input.bool(true, 'Профиль по последним N барам (как на левом крае)', group = G_POC, tooltip = 'Гистограмма строится по последним N барам — она покрывает весь видимый ценовой диапазон, а не только сегодняшний день. Именно так выглядят профили на левом крае графика.')
int    iPocRangeBars= input.int(1000,  'Сколько баров в профиле', minval = 100, maxval = 3000, step = 50, group = G_POC, tooltip = 'Максимум баров, которые держим в буфере. Если окно шире — профиль посчитается по последним N барам.')
bool   iPocVisOnly  = input.bool(true, 'Считать только видимые бары', group = G_POC, tooltip = 'Профиль строится ровно по тому участку, который видно на экране — как Fixed Range Volume Profile. При прокрутке профиль пересчитывается.')
int    iPocProfBins = input.int(32,    'Бинов на гистограмме', minval = 8, maxval = 120, group = G_POC, tooltip = 'Меньше бинов = толще и читаемее полосы. 30–40 — оптимум.')
int    iPocProfPct  = input.int(25,    'Ширина профиля, % окна', minval = 5, maxval = 45, group = G_POC, tooltip = 'Доля ширины видимого окна, которую занимает самая длинная полоса профиля.')
color  iPocProfUpCol= input.color(#f23645, 'профиль: выше цены (сопротивление)', group = G_POC)
color  iPocProfDnCol= input.color(#089981, 'профиль: ниже цены (поддержка)',    group = G_POC)
color  iPocProfPocCol=input.color(#ffd400,'профиль: бин POC',                  group = G_POC)
bool   iPocHvnOn    = input.bool(true, 'Пунктиры от важных точек (HVN)', group = G_POC, tooltip = 'Крупные бины профиля (кроме POC) — места, где тоже наторговано много; к ним цена возвращается.')
float  iPocHvnPct   = input.float(70,  'Порог HVN, % от объёма POC', minval = 30, maxval = 95, group = G_POC)
bool   iPocLbls     = input.bool(true, 'Подписи POC/VAH/VAL слева', group = G_POC)
color  iLevColD  = input.color(#9aa4b2, 'Цвет PDH / PDL',            group = G_LVL)
color  iLevColW  = input.color(#d4a15a, 'Цвет PWH / PWL',            group = G_LVL)
color  iLevColS1 = input.color(#5aa9d4, 'Цвет свинга 1',             group = G_LVL)
color  iLevColS2 = input.color(#a48ad4, 'Цвет свинга 2',             group = G_LVL)

bool   iAlerts     = input.bool(true, 'alert() с текстом сигнала',    group = G_AL)

bool   iEmaOn      = input.bool(true,  'Показывать EMA',              group = G_EMA)
bool   iEmaLabels  = input.bool(true,  'Подписи справа (ТФ·период)',   group = G_EMA)
bool   iEmaStraight = input.bool(true,  'Ровная линия между барами старшего ТФ', group = G_EMA, tooltip = 'Вкл: линия линейно проводится от прошлого закрытия старшего ТФ к новому — без «трамплина» из ступенек. Выкл: классические полки по значению закрытого бара.')
int    iEmaWidth   = input.int(1,      'Толщина линий',                minval = 1, maxval = 3, group = G_EMA)
int    iEmaSmooth  = input.int(2,      'Сглаживание углов, баров (1 = без доп. сглаживания)', minval = 1, maxval = 50, group = G_EMA, tooltip = 'Ступеньки убирает линейная проводка между закрытиями старшего бара (автоматически). Этот параметр лишь скругляет изломы на стыках баров старшего ТФ: 1 — без сглаживания, 2–4 — мягче, больше 10 — заметное запаздывание.')
float  iClusterAtr = input.float(0.5,  'Порог кластера EMA, ATR',       minval = 0.1, step = 0.1, group = G_EMA, tooltip = 'Если несколько EMA стоят ближе этого расстояния — кластер: сильнейшая остаётся яркой, остальные тускнеют.')
int    iClusterMin = input.int(3,      'EMA в кластере для затухания', minval = 2, maxval = 12, group = G_EMA)
int    iFadeAdd    = input.int(16,     'Доп. прозрачность слабых',     minval = 0, maxval = 50, group = G_EMA)
int    iEmaBright  = input.int(6,      'Яркость линий (сдвиг прозрачности)', minval = 0, maxval = 30, group = G_EMA, tooltip = 'Больше = линии ярче. 0 = базовые значения, 30 = максимум.')

// Набор по умолчанию (самые важные): 15m 20/50, 1H 50/200, 4H 50, 1D 20/200. Период 0 = выключить.
// У каждой линии свой цвет (4 ТФ x 3 слота) — линии в пучке не сливаются.
bool   iTfOn1      = input.bool(true,  'ТФ 1', inline = 'tf1', group = G_EMA, tooltip = 'Порядок в строке: [вкл] [ТФ] [период 1] [период 2] [период 3]. Цвета — ниже: ТФ N · цвет 1/2/3.')
string iTf1        = input.timeframe('15', '', inline = 'tf1', group = G_EMA)
int    pA1         = input.int(20, '', inline = 'tf1', minval = 0, maxval = 1000, group = G_EMA, tooltip = 'Период 1. 0 = линия выключена.')
int    pB1         = input.int(50, '', inline = 'tf1', minval = 0, maxval = 1000, group = G_EMA, tooltip = 'Период 2. 0 = линия выключена.')
int    pC1         = input.int(0,  '', inline = 'tf1', minval = 0, maxval = 1000, group = G_EMA, tooltip = 'Период 3. 0 = линия выключена.')
color  iColA1      = input.color(#22e39a, 'ТФ 1 · цвет 1', group = G_EMA)
color  iColB1      = input.color(#00d9d9, 'ТФ 1 · цвет 2', group = G_EMA)
color  iColC1      = input.color(#6ee7ff, 'ТФ 1 · цвет 3', group = G_EMA)

bool   iTfOn2      = input.bool(true,  'ТФ 2', inline = 'tf2', group = G_EMA, tooltip = 'Порядок в строке: [вкл] [ТФ] [период 1] [период 2] [период 3]. Цвета — ниже: ТФ N · цвет 1/2/3.')
string iTf2        = input.timeframe('60', '', inline = 'tf2', group = G_EMA)
int    pA2         = input.int(50, '', inline = 'tf2', minval = 0, maxval = 1000, group = G_EMA, tooltip = 'Период 1. 0 = линия выключена.')
int    pB2         = input.int(200, '', inline = 'tf2', minval = 0, maxval = 1000, group = G_EMA, tooltip = 'Период 2. 0 = линия выключена.')
int    pC2         = input.int(0,  '', inline = 'tf2', minval = 0, maxval = 1000, group = G_EMA, tooltip = 'Период 3. 0 = линия выключена.')
color  iColA2      = input.color(#4d9bff, 'ТФ 2 · цвет 1', group = G_EMA)
color  iColB2      = input.color(#ff8a3d, 'ТФ 2 · цвет 2', group = G_EMA)
color  iColC2      = input.color(#8f7bff, 'ТФ 2 · цвет 3', group = G_EMA)

bool   iTfOn3      = input.bool(true,  'ТФ 3', inline = 'tf3', group = G_EMA, tooltip = 'Порядок в строке: [вкл] [ТФ] [период 1] [период 2] [период 3]. Цвета — ниже: ТФ N · цвет 1/2/3.')
string iTf3        = input.timeframe('240', '', inline = 'tf3', group = G_EMA)
int    pA3         = input.int(50, '', inline = 'tf3', minval = 0, maxval = 1000, group = G_EMA, tooltip = 'Период 1. 0 = линия выключена.')
int    pB3         = input.int(0,  '', inline = 'tf3', minval = 0, maxval = 1000, group = G_EMA, tooltip = 'Период 2. 0 = линия выключена.')
int    pC3         = input.int(0,  '', inline = 'tf3', minval = 0, maxval = 1000, group = G_EMA, tooltip = 'Период 3. 0 = линия выключена.')
color  iColA3      = input.color(#c070ff, 'ТФ 3 · цвет 1', group = G_EMA)
color  iColB3      = input.color(#ff5ce0, 'ТФ 3 · цвет 2', group = G_EMA)
color  iColC3      = input.color(#ff4d7d, 'ТФ 3 · цвет 3', group = G_EMA)

bool   iTfOn4      = input.bool(true,  'ТФ 4', inline = 'tf4', group = G_EMA, tooltip = 'Порядок в строке: [вкл] [ТФ] [период 1] [период 2] [период 3]. Цвета — ниже: ТФ N · цвет 1/2/3.')
string iTf4        = input.timeframe('D', '', inline = 'tf4', group = G_EMA)
int    pA4         = input.int(200, '', inline = 'tf4', minval = 0, maxval = 1000, group = G_EMA, tooltip = 'Период 1. 0 = линия выключена.')
int    pB4         = input.int(20,  '', inline = 'tf4', minval = 0, maxval = 1000, group = G_EMA, tooltip = 'Период 2. 0 = линия выключена.')
int    pC4         = input.int(0,   '', inline = 'tf4', minval = 0, maxval = 1000, group = G_EMA, tooltip = 'Период 3. 0 = линия выключена.')
color  iColA4      = input.color(#ffc93a, 'ТФ 4 · цвет 1', group = G_EMA)
color  iColB4      = input.color(#b8e986, 'ТФ 4 · цвет 2', group = G_EMA)
color  iColC4      = input.color(#ff5252, 'ТФ 4 · цвет 3', group = G_EMA)

color  cBull       = input.color(#089981, 'Бычий',  inline = 'c1', group = G_COL)
color  cBear       = input.color(#F23645, 'Медвежий', inline = 'c1', group = G_COL)
color  cBullOB     = input.color(color.new(#089981, 78), 'Бычий OB',  inline = 'c2', group = G_COL)
color  cBearOB     = input.color(color.new(#f23645, 78), 'Медвежий OB', inline = 'c2', group = G_COL)
color  cBullFvg    = input.color(color.new(#00ff68, 82), 'Бычий FVG', inline = 'c3', group = G_COL)
color  cBearFvg    = input.color(color.new(#ff0008, 82), 'Медвежий FVG', inline = 'c3', group = G_COL)

// ---- Пресеты ----
string iPreset = input.string('Пользовательский', 'Пресет', options = ['Пользовательский', 'Интрадей 15m', 'Свинг 1H', 'Только A+', 'Оригинал LuxAlgo', 'Чистый график'], group = G_PRE, tooltip = 'Один переключатель вместо десятка полей. Пользовательский = всё как выставлено вручную. Интрадей 15m: ТФ EMA 15/60/240/D. Свинг 1H: ТФ EMA 60/240/D/W, свинги длиннее, зоны не скрываются по расстоянию. Только A+: на графике остаются лишь A+ зоны. Чистый график: EMA и уровни выключены, только A+ зоны. Оригинал LuxAlgo: как в исходном индикаторе — внутренние OB включены, без дедупликации и без отбраковки пробитых зон, митигация по High/Low, далёкие зоны не скрываются.')

// ---- Дашборд и статистика ----
bool   iDash     = input.bool(true,  'Показывать дашборд (правый верхний угол)', group = G_DASH)
bool   iStats    = input.bool(true,  'Считать статистику A+ зон',   group = G_DASH, tooltip = 'Для каждой A+ зоны: ждём касания, затем смотрим, ушла цена на N ATR (отскок) или зона пробита. Процент = отскоки / все проверенные зоны.')
float  iStatAtr  = input.float(1.0,  'Отскок = уход от зоны, ATR',  minval = 0.2, maxval = 5, step = 0.1, group = G_DASH)
bool   iStatClose = input.bool(false, 'Отскок считать по закрытию бара', group = G_DASH, tooltip = 'Выкл: достаточно, чтобы цена (фитилём) ушла на N ATR от зоны — метрика мягче. Вкл: нужно закрытие бара за этим уровнем — строже и ближе к реальному исполнению.')
int    iStatExpire = input.int(50,    'Считать истёкшей через N баров', minval = 5, maxval = 500, group = G_DASH, tooltip = 'Если цена коснулась зоны, но за N баров не ушла на ATR и зону не пробила — считаем её «истёкшей» (не успех и не провал), чтобы она не висела в статистике вечно.')

bool   iSignalMarks   = input.bool(true,  'Метки BUY / SELL у A+ зон',  group = G_SIG, tooltip = 'Метка ставится в момент, когда цена впервые вошла в A+ зону: BUY — у поддержки, SELL — у сопротивления.')
bool   iSignalGate    = input.bool(true,  'Только если статистика этой стороны выше порога', group = G_SIG)
int    iSignalMinRate = input.int(55,     'Мин. win-rate стороны, %',    minval = 30, maxval = 95, group = G_SIG)
int    iSignalMinN    = input.int(8,      'Мин. выборка, проверенных зон', minval = 1, maxval = 500, group = G_SIG, tooltip = 'Пока не набрано столько разрешённых зон, ярких меток не будет (только тусклые). После обновления индикатора статистика начинается с нуля — не пугайтесь.')
bool   iSignalWeak    = input.bool(true,  'Слабые метки тоже показывать (тускло)', group = G_SIG)
bool   iSignalStruct  = input.bool(false, 'Только в сторону структуры',  group = G_SIG, tooltip = 'Вкл: BUY только при бычьей структуре, SELL — только при медвежьей.')
int    iSignalMax     = input.int(20,     'Макс. меток на графике',      minval = 1, maxval = 100, group = G_SIG)
int    iSignalMinPct   = input.int(80,    'Мин. конфлюенс для метки, % от возможного', minval = 30, maxval = 100, group = G_SIG, tooltip = '100 = метка только у зон, где совпало ВСЁ доступное. Это самые вероятные места отскока и резко меньше меток.')
int    iSignalCool    = input.int(10,     'Мин. пауза между метками, баров', minval = 0, maxval = 100, group = G_SIG, tooltip = 'Защита от пачки меток подряд. 0 = без паузы.')

// ---- Алерты на зоны ----
bool   iAlertNear     = input.bool(true, 'Алерт: подход к A+ зоне',        group = G_AL)
float  iAlertNearAtr  = input.float(0.5,'Порог подхода, ATR',              minval = 0.1, maxval = 5, step = 0.1, group = G_AL)
bool   iAlertBreak    = input.bool(true, 'Алерт: зона сломана',            group = G_AL)
int    iAlertCool     = input.int(10,    'Пауза между алертами, баров',    minval = 1, maxval = 200, group = G_AL)

// ---------------------------------------------------------------------------------------------------------------------
// ПРЕСЕТЫ -> эффективные значения (сами input.* не меняются, меняется то, что применяется)
// ---------------------------------------------------------------------------------------------------------------------
bool   eEmaOn     = iPreset == 'Чистый график' ? false : iEmaOn
bool   eLevOn     = iPreset == 'Чистый график' ? false : iLevOn
bool   eShowPD    = iPreset == 'Чистый график' ? false : iShowPD
bool   eStructLbl = iPreset == 'Чистый график' ? false : iShowStructLbl
bool   eAplusOnly = (iPreset == 'Только A+' or iPreset == 'Чистый график') ? true : iAplusOnly
bool   eHideFar   = (iPreset == 'Свинг 1H' or iPreset == 'Оригинал LuxAlgo') ? false : iHideFar
float  eZoneAtr   = iPreset == 'Свинг 1H' ? 15.0 : iZoneAtr
int    eMaxOB     = iPreset == 'Свинг 1H' ? 6 : (iPreset == 'Чистый график' ? 4 : (iPreset == 'Оригинал LuxAlgo' ? 6 : iMaxOB))
int    eMaxFvg    = iPreset == 'Свинг 1H' ? 6 : (iPreset == 'Чистый график' ? 4 : (iPreset == 'Оригинал LuxAlgo' ? 6 : iMaxFvg))
int    eSwingLegs = iPreset == 'Свинг 1H' ? 8 : iSwingLegs
// «Оригинал LuxAlgo»: внутренние OB включены, без дедупликации и без отбраковки пробитых зон,
// митигация по High/Low, минимальная высота зоны не проверяется, далёкие зоны не скрываются.
bool   eShowIntOB   = iPreset == 'Оригинал LuxAlgo' ? true  : iShowIntOB
bool   eObDedup     = iPreset == 'Оригинал LuxAlgo' ? false : iObDedup
bool   eObSkipBroken= iPreset == 'Оригинал LuxAlgo' ? false : iObSkipBroken
float  eMinOBAtr    = iPreset == 'Оригинал LuxAlgo' ? 0.0   : iMinOBAtr
string eMitMode     = iPreset == 'Оригинал LuxAlgo' ? 'Wick' : iMitMode

// ТФ EMA: Интрадей 15m = 15/60/240/D, Свинг 1H = 60/240/D/W, иначе — как в настройках
string eTf1 = iPreset == 'Интрадей 15m' ? '15' : (iPreset == 'Свинг 1H' ? '60'  : iTf1)
string eTf2 = iPreset == 'Интрадей 15m' ? '60' : (iPreset == 'Свинг 1H' ? '240' : iTf2)
string eTf3 = iPreset == 'Интрадей 15m' ? '240': (iPreset == 'Свинг 1H' ? 'D'   : iTf3)
string eTf4 = iPreset == 'Интрадей 15m' ? 'D'  : (iPreset == 'Свинг 1H' ? 'W'   : iTf4)
string eLevTf1 = iPreset == 'Свинг 1H' ? '240' : iLevTf1
string eLevTf2 = iPreset == 'Свинг 1H' ? 'D'   : iLevTf2

// ---------------------------------------------------------------------------------------------------------------------
// TYPES
// ---------------------------------------------------------------------------------------------------------------------
type stState
    float hLvl    = na
    int   hIdx    = na
    int   hTime   = na
    bool  hBroken = false
    float lLvl    = na
    int   lIdx    = na
    int   lTime   = na
    bool  lBroken = false
    int   bias    = 0

type obZone
    float top       = na
    float bot       = na
    int   bias      = 0
    int   tTime     = na
    box   bx        = na
    bool  mit       = false
    int   born      = 0
    bool  strong    = false
    color col       = na
    bool  touched   = false
    bool  done      = false
    int   score     = 0
    int   smax      = 1
    int   mask      = 0
    float maxEx     = na
    float minEx     = na

type fvgZone
    float top  = na
    float bot  = na
    int   bias = 0
    box   bx   = na
    bool  mit  = false
    int   born = 0
    color col  = na

type pivotPt
    float lvl  = na
    int   tTime = na
    int   bIdx  = na

// ---------------------------------------------------------------------------------------------------------------------
// STATE
// ---------------------------------------------------------------------------------------------------------------------
var stState swingSt = stState.new()
var stState intSt   = stState.new()

var array<obZone>  swingOB   = array.new<obZone>()
var array<obZone>  intOB     = array.new<obZone>()
var array<fvgZone> fvgArr    = array.new<fvgZone>()
var array<pivotPt> pHiArr    = array.new<pivotPt>()
var array<pivotPt> pLoArr    = array.new<pivotPt>()
var array<line>    eqhLines  = array.new<line>()
var array<line>    eqlLines  = array.new<line>()

var float prevHiLvl = na
var int   statWinSup   = 0
var int   statWinRes   = 0
var int   statLossSup  = 0
var int   statLossRes  = 0
var int   statExp      = 0
var int   statCreated  = 0
var int   statRemoved  = 0
var int   statVisible  = 0
var int   lastZoneAlert = -100000
var int   lastSigBarSup = -100000
var int   lastSigBarRes = -100000
var float prevLoLvl = na

// Очереди объектов структуры: держим только последние N линий/меток (иначе чарт зарастает «полосками»)
var array<line>  swBullLines = array.new<line>()
var array<label> swBullLabel = array.new<label>()
var array<line>  swBearLines = array.new<line>()
var array<label> swBearLabel = array.new<label>()
var array<line>  inBullLines = array.new<line>()
var array<label> inBullLabel = array.new<label>()
var array<line>  inBearLines = array.new<line>()
var array<label> inBearLabel = array.new<label>()
var array<label> eqLabels    = array.new<label>()
var array<label> sigLabels   = array.new<label>()

// 3 зоны Premium / Equilibrium / Discount (создаются один раз, переиспользуются)
var box   pdPrem = box.new(na, na, na, na, xloc = xloc.bar_time, extend = extend.right, bgcolor = color.new(cBear, 90), border_color = color.new(cBear, 75))
var box   pdEq   = box.new(na, na, na, na, xloc = xloc.bar_time, extend = extend.right, bgcolor = color.new(color.gray, 88), border_color = color.new(color.gray, 75))
var box   pdDisc = box.new(na, na, na, na, xloc = xloc.bar_time, extend = extend.right, bgcolor = color.new(cBull, 90), border_color = color.new(cBull, 75))
var label pdPremLb = label.new(na, na, 'Premium',     xloc = xloc.bar_time, color = color(na), textcolor = cBear, style = label.style_label_down, size = size.tiny)
var label pdEqLb   = label.new(na, na, 'Equilibrium', xloc = xloc.bar_time, color = color(na), textcolor = color.gray, style = label.style_label_left, size = size.tiny)
var label pdDiscLb = label.new(na, na, 'Discount',    xloc = xloc.bar_time, color = color(na), textcolor = cBull, style = label.style_label_up, size = size.tiny)

// ---------------------------------------------------------------------------------------------------------------------
// ATR, EMA старших ТФ и HTF-направление (нужны и для отрисовки, и для оценки конфлюенса зон)
// ---------------------------------------------------------------------------------------------------------------------
float atrRaw = ta.atr(200)
float atrRef = na(atrRaw) ? syminfo.mintick : atrRaw

// HTF-фильтр: [1] + lookahead_on — единственный нерепейнтящий паттерн
string htfTf   = iHtfTf == '' ? timeframe.period : iHtfTf
float  htfEma  = request.security(syminfo.tickerid, htfTf, ta.ema(close, iHtfLen)[1], lookahead = barmerge.lookahead_on)
int    htfBias = iHtfTf == '' ? 0 : (close > nz(htfEma, close) ? 1 : -1)

// @function  Читаемое имя таймфрейма: 60 -> 1H, 240 -> 4H, D -> 1D, W -> 1W
f_tfName(simple string tf) =>
    int sec = timeframe.in_seconds(tf)
    string res = tf
    if not na(sec)
        if sec >= 604800
            res := str.tostring(int(sec / 604800)) + 'W'
        else if sec >= 86400
            res := str.tostring(int(sec / 86400)) + 'D'
        else if sec >= 3600
            res := str.tostring(int(sec / 3600)) + 'H'
        else
            res := str.tostring(int(sec / 60)) + 'm'
    res

// EMA: 4 ТФ x до 3 периодов = до 12 линий; включено по умолчанию 7 самых важных.
// Значение берётся с ЗАКРЫТОГО бара старшего ТФ ([1] + lookahead_on) — без репейнта.
// Внутри своего бара это значение постоянно, поэтому «в лоб» получаются ступеньки.
// Решение: между двумя закрытиями старшего бара линия ПРОВОДИТСЯ линейно от прошлого
// значения к новому (fracN = доля пройденной части бара). Получается ровная непрерывная
// кривая: на первом баре нового бара ТФ линия стоит ровно там, где закончилась предыдущая.

// @function  EMA старшего ТФ, только с закрытого бара (нерепейнт)
f_htfEma(simple string tf, int len) =>
    request.security(syminfo.tickerid, tf, ta.ema(close, math.max(len, 1))[1], lookahead = barmerge.lookahead_on)

// Доля пройденной части бара старшего ТФ — по КОЛИЧЕСТВУ баров графика, а не по часам
// (так корректно работают короткие торговые сессии и выходные).
int tHtf1 = time(eTf1)
int tHtf2 = time(eTf2)
int tHtf3 = time(eTf3)
int tHtf4 = time(eTf4)

var int nb1 = 0
var int np1 = 0
var int nb2 = 0
var int np2 = 0
var int nb3 = 0
var int np3 = 0
var int nb4 = 0
var int np4 = 0

if ta.change(tHtf1) != 0
    np1 := nb1
    nb1 := 0
if ta.change(tHtf2) != 0
    np2 := nb2
    nb2 := 0
if ta.change(tHtf3) != 0
    np3 := nb3
    nb3 := 0
if ta.change(tHtf4) != 0
    np4 := nb4
    nb4 := 0
nb1 += 1
nb2 += 1
nb3 += 1
nb4 += 1

// frac = 0 на первом баре старшего бара, 1 к его концу (1.0 = нет данных о длине, без проводки)
float frac1 = iEmaStraight and np1 > 1 ? math.min(1.0, 1.0 * (nb1 - 1) / np1) : 1.0
float frac2 = iEmaStraight and np2 > 1 ? math.min(1.0, 1.0 * (nb2 - 1) / np2) : 1.0
float frac3 = iEmaStraight and np3 > 1 ? math.min(1.0, 1.0 * (nb3 - 1) / np3) : 1.0
float frac4 = iEmaStraight and np4 > 1 ? math.min(1.0, 1.0 * (nb4 - 1) / np4) : 1.0

// ступенька (закрытый старший бар) -> прошлое значение -> линейная проводка -> лёгкое сглаживание углов
float stepA1 = f_htfEma(eTf1, pA1)
float stepA2 = f_htfEma(eTf1, pB1)
float stepA3 = f_htfEma(eTf1, pC1)
float stepB1 = f_htfEma(eTf2, pA2)
float stepB2 = f_htfEma(eTf2, pB2)
float stepB3 = f_htfEma(eTf2, pC2)
float stepC1 = f_htfEma(eTf3, pA3)
float stepC2 = f_htfEma(eTf3, pB3)
float stepC3 = f_htfEma(eTf3, pC3)
float stepD1 = f_htfEma(eTf4, pA4)
float stepD2 = f_htfEma(eTf4, pB4)
float stepD3 = f_htfEma(eTf4, pC4)

float prvA1 = ta.valuewhen(stepA1 != nz(stepA1[1], stepA1), nz(stepA1[1], stepA1), 0)
float prvA2 = ta.valuewhen(stepA2 != nz(stepA2[1], stepA2), nz(stepA2[1], stepA2), 0)
float prvA3 = ta.valuewhen(stepA3 != nz(stepA3[1], stepA3), nz(stepA3[1], stepA3), 0)
float prvB1 = ta.valuewhen(stepB1 != nz(stepB1[1], stepB1), nz(stepB1[1], stepB1), 0)
float prvB2 = ta.valuewhen(stepB2 != nz(stepB2[1], stepB2), nz(stepB2[1], stepB2), 0)
float prvB3 = ta.valuewhen(stepB3 != nz(stepB3[1], stepB3), nz(stepB3[1], stepB3), 0)
float prvC1 = ta.valuewhen(stepC1 != nz(stepC1[1], stepC1), nz(stepC1[1], stepC1), 0)
float prvC2 = ta.valuewhen(stepC2 != nz(stepC2[1], stepC2), nz(stepC2[1], stepC2), 0)
float prvC3 = ta.valuewhen(stepC3 != nz(stepC3[1], stepC3), nz(stepC3[1], stepC3), 0)
float prvD1 = ta.valuewhen(stepD1 != nz(stepD1[1], stepD1), nz(stepD1[1], stepD1), 0)
float prvD2 = ta.valuewhen(stepD2 != nz(stepD2[1], stepD2), nz(stepD2[1], stepD2), 0)
float prvD3 = ta.valuewhen(stepD3 != nz(stepD3[1], stepD3), nz(stepD3[1], stepD3), 0)

float linA1 = na(prvA1) ? stepA1 : prvA1 + (stepA1 - prvA1) * frac1
float linA2 = na(prvA2) ? stepA2 : prvA2 + (stepA2 - prvA2) * frac1
float linA3 = na(prvA3) ? stepA3 : prvA3 + (stepA3 - prvA3) * frac1
float linB1 = na(prvB1) ? stepB1 : prvB1 + (stepB1 - prvB1) * frac2
float linB2 = na(prvB2) ? stepB2 : prvB2 + (stepB2 - prvB2) * frac2
float linB3 = na(prvB3) ? stepB3 : prvB3 + (stepB3 - prvB3) * frac2
float linC1 = na(prvC1) ? stepC1 : prvC1 + (stepC1 - prvC1) * frac3
float linC2 = na(prvC2) ? stepC2 : prvC2 + (stepC2 - prvC2) * frac3
float linC3 = na(prvC3) ? stepC3 : prvC3 + (stepC3 - prvC3) * frac3
float linD1 = na(prvD1) ? stepD1 : prvD1 + (stepD1 - prvD1) * frac4
float linD2 = na(prvD2) ? stepD2 : prvD2 + (stepD2 - prvD2) * frac4
float linD3 = na(prvD3) ? stepD3 : prvD3 + (stepD3 - prvD3) * frac4

float emaA1 = ta.ema(linA1, iEmaSmooth)
float emaA2 = ta.ema(linA2, iEmaSmooth)
float emaA3 = ta.ema(linA3, iEmaSmooth)
float emaB1 = ta.ema(linB1, iEmaSmooth)
float emaB2 = ta.ema(linB2, iEmaSmooth)
float emaB3 = ta.ema(linB3, iEmaSmooth)
float emaC1 = ta.ema(linC1, iEmaSmooth)
float emaC2 = ta.ema(linC2, iEmaSmooth)
float emaC3 = ta.ema(linC3, iEmaSmooth)
float emaD1 = ta.ema(linD1, iEmaSmooth)
float emaD2 = ta.ema(linD2, iEmaSmooth)
float emaD3 = ta.ema(linD3, iEmaSmooth)

// Сбор значений включённых EMA — для кластерного анализа прозрачности
var array<float> emaVals = array.new<float>()
var array<int>   emaRnk  = array.new<int>()
array.clear(emaVals)
array.clear(emaRnk)
if iTfOn1 and pA1 > 0 and not na(emaA1)
    emaVals.push(emaA1)
    emaRnk.push(10000 + pA1)
if iTfOn1 and pB1 > 0 and not na(emaA2)
    emaVals.push(emaA2)
    emaRnk.push(10000 + pB1)
if iTfOn1 and pC1 > 0 and not na(emaA3)
    emaVals.push(emaA3)
    emaRnk.push(10000 + pC1)
if iTfOn2 and pA2 > 0 and not na(emaB1)
    emaVals.push(emaB1)
    emaRnk.push(20000 + pA2)
if iTfOn2 and pB2 > 0 and not na(emaB2)
    emaVals.push(emaB2)
    emaRnk.push(20000 + pB2)
if iTfOn2 and pC2 > 0 and not na(emaB3)
    emaVals.push(emaB3)
    emaRnk.push(20000 + pC2)
if iTfOn3 and pA3 > 0 and not na(emaC1)
    emaVals.push(emaC1)
    emaRnk.push(30000 + pA3)
if iTfOn3 and pB3 > 0 and not na(emaC2)
    emaVals.push(emaC2)
    emaRnk.push(30000 + pB3)
if iTfOn3 and pC3 > 0 and not na(emaC3)
    emaVals.push(emaC3)
    emaRnk.push(30000 + pC3)
if iTfOn4 and pA4 > 0 and not na(emaD1)
    emaVals.push(emaD1)
    emaRnk.push(40000 + pA4)
if iTfOn4 and pB4 > 0 and not na(emaD2)
    emaVals.push(emaD2)
    emaRnk.push(40000 + pB4)
if iTfOn4 and pC4 > 0 and not na(emaD3)
    emaVals.push(emaD3)
    emaRnk.push(40000 + pC4)
// @function  Прозрачность: чем длиннее период и старше ТФ — тем плотнее линия; iEmaBright сдвигает всё к яркому
f_emaTransp(int tfIdx, int len) =>
    int base = len >= 200 ? 36 : (len >= 100 ? 44 : (len >= 50 ? 48 : 56))
    math.max(10, math.min(88, base - (tfIdx - 1) * 5 - iEmaBright))

// @function  Итоговая прозрачность с учётом кластера: rank = ТФ*10000 + период (в пучке ярче остаётся старшая и самая длинная)
f_emaColor(int rank, float v, color base, int baseTransp) =>
    int  cnt  = 0
    bool dom  = true
    if array.size(emaVals) > 0
        for i = 0 to array.size(emaVals) - 1
            float ov = array.get(emaVals, i)
            if math.abs(ov - v) <= iClusterAtr * atrRef
                cnt += 1
                if array.get(emaRnk, i) > rank
                    dom := false
    int t = baseTransp
    if cnt >= iClusterMin and not dom
        t := int(math.min(96, baseTransp + iFadeAdd))
    color.new(base, t)

// цвета линий на текущем баре: у каждой линии свой цвет, плотность зависит от периода и ТФ
color clrA1 = f_emaColor(10000 + pA1, emaA1, iColA1, f_emaTransp(1, pA1))
color clrA2 = f_emaColor(10000 + pB1, emaA2, iColB1, f_emaTransp(1, pB1))
color clrA3 = f_emaColor(10000 + pC1, emaA3, iColC1, f_emaTransp(1, pC1))
color clrB1 = f_emaColor(20000 + pA2, emaB1, iColA2, f_emaTransp(2, pA2))
color clrB2 = f_emaColor(20000 + pB2, emaB2, iColB2, f_emaTransp(2, pB2))
color clrB3 = f_emaColor(20000 + pC2, emaB3, iColC2, f_emaTransp(2, pC2))
color clrC1 = f_emaColor(30000 + pA3, emaC1, iColA3, f_emaTransp(3, pA3))
color clrC2 = f_emaColor(30000 + pB3, emaC2, iColB3, f_emaTransp(3, pB3))
color clrC3 = f_emaColor(30000 + pC3, emaC3, iColC3, f_emaTransp(3, pC3))
color clrD1 = f_emaColor(40000 + pA4, emaD1, iColA4, f_emaTransp(4, pA4))
color clrD2 = f_emaColor(40000 + pB4, emaD2, iColB4, f_emaTransp(4, pB4))
color clrD3 = f_emaColor(40000 + pC4, emaD3, iColC4, f_emaTransp(4, pC4))
// подписи EMA у правого края
var label lbA1 = label.new(na, na, '', xloc = xloc.bar_time, color = color(na), style = label.style_label_left, size = size.tiny)
var label lbA2 = label.new(na, na, '', xloc = xloc.bar_time, color = color(na), style = label.style_label_left, size = size.tiny)
var label lbA3 = label.new(na, na, '', xloc = xloc.bar_time, color = color(na), style = label.style_label_left, size = size.tiny)
var label lbB1 = label.new(na, na, '', xloc = xloc.bar_time, color = color(na), style = label.style_label_left, size = size.tiny)
var label lbB2 = label.new(na, na, '', xloc = xloc.bar_time, color = color(na), style = label.style_label_left, size = size.tiny)
var label lbB3 = label.new(na, na, '', xloc = xloc.bar_time, color = color(na), style = label.style_label_left, size = size.tiny)
var label lbC1 = label.new(na, na, '', xloc = xloc.bar_time, color = color(na), style = label.style_label_left, size = size.tiny)
var label lbC2 = label.new(na, na, '', xloc = xloc.bar_time, color = color(na), style = label.style_label_left, size = size.tiny)
var label lbC3 = label.new(na, na, '', xloc = xloc.bar_time, color = color(na), style = label.style_label_left, size = size.tiny)
var label lbD1 = label.new(na, na, '', xloc = xloc.bar_time, color = color(na), style = label.style_label_left, size = size.tiny)
var label lbD2 = label.new(na, na, '', xloc = xloc.bar_time, color = color(na), style = label.style_label_left, size = size.tiny)
var label lbD3 = label.new(na, na, '', xloc = xloc.bar_time, color = color(na), style = label.style_label_left, size = size.tiny)

// @function  Подпись EMA у правого края: показать (ТФ·период, цвет линии) или спрятать, если линия выключена
f_setEmaLabel(label lb, bool show, float v, int t, string txt, color c) =>
    if show and not na(v)
        label.set_xy(lb, t, v)
        label.set_color(lb, color(na))
        label.set_text(lb, txt)
        label.set_textcolor(lb, c)
    else
        label.set_color(lb, color.new(color.black, 100))
        label.set_text(lb, '')

// ---------------------------------------------------------------------------------------------------------------------
// КЛЮЧЕВЫЕ УРОВНИ СТАРШЕГО ТФ: экстремумы вчера/недели + последние свинги 1H/4H
// Всё берётся только с ЗАКРЫТЫХ баров старшего ТФ ([1] + lookahead_on) — без репейнта.
// ---------------------------------------------------------------------------------------------------------------------
// @function  Последний подтверждённый свинг-максимум старшего ТФ
f_swingHi(simple string tf, simple int legs) =>
    request.security(syminfo.tickerid, tf, ta.valuewhen(not na(ta.pivothigh(high, legs, legs)), ta.pivothigh(high, legs, legs), 0)[1], lookahead = barmerge.lookahead_on)

// @function  Последний подтверждённый свинг-минимум старшего ТФ
f_swingLo(simple string tf, simple int legs) =>
    request.security(syminfo.tickerid, tf, ta.valuewhen(not na(ta.pivotlow(low, legs, legs)), ta.pivotlow(low, legs, legs), 0)[1], lookahead = barmerge.lookahead_on)

float levPdH = request.security(syminfo.tickerid, 'D', high[1], lookahead = barmerge.lookahead_on)
float levPdL = request.security(syminfo.tickerid, 'D', low[1],  lookahead = barmerge.lookahead_on)
float levPwH = request.security(syminfo.tickerid, 'W', high[1], lookahead = barmerge.lookahead_on)
float levPwL = request.security(syminfo.tickerid, 'W', low[1],  lookahead = barmerge.lookahead_on)
float levS1H = f_swingHi(eLevTf1, iLevLegs)
float levS1L = f_swingLo(eLevTf1, iLevLegs)
float levS2H = f_swingHi(eLevTf2, iLevLegs)
float levS2L = f_swingLo(eLevTf2, iLevLegs)

// 8 линий и 8 подписей — создаются один раз, дальше только обновляются (без мусора в объектах)
var line lnPdH = line.new(time, close, time + 1, close, xloc = xloc.bar_time, extend = extend.right, style = line.style_dashed, width = 1)
var line lnPdL = line.new(time, close, time + 1, close, xloc = xloc.bar_time, extend = extend.right, style = line.style_dashed, width = 1)
var line lnPwH = line.new(time, close, time + 1, close, xloc = xloc.bar_time, extend = extend.right, style = line.style_dashed, width = 1)
var line lnPwL = line.new(time, close, time + 1, close, xloc = xloc.bar_time, extend = extend.right, style = line.style_dashed, width = 1)
var line lnS1H = line.new(time, close, time + 1, close, xloc = xloc.bar_time, extend = extend.right, style = line.style_dotted, width = 1)
var line lnS1L = line.new(time, close, time + 1, close, xloc = xloc.bar_time, extend = extend.right, style = line.style_dotted, width = 1)
var line lnS2H = line.new(time, close, time + 1, close, xloc = xloc.bar_time, extend = extend.right, style = line.style_dotted, width = 1)
var line lnS2L = line.new(time, close, time + 1, close, xloc = xloc.bar_time, extend = extend.right, style = line.style_dotted, width = 1)

var label lbPdH = label.new(bar_index, close, '', xloc = xloc.bar_index, color = color(na), style = label.style_label_left, size = size.tiny)
var label lbPdL = label.new(bar_index, close, '', xloc = xloc.bar_index, color = color(na), style = label.style_label_left, size = size.tiny)
var label lbPwH = label.new(bar_index, close, '', xloc = xloc.bar_index, color = color(na), style = label.style_label_left, size = size.tiny)
var label lbPwL = label.new(bar_index, close, '', xloc = xloc.bar_index, color = color(na), style = label.style_label_left, size = size.tiny)
var label lbS1H = label.new(bar_index, close, '', xloc = xloc.bar_index, color = color(na), style = label.style_label_left, size = size.tiny)
var label lbS1L = label.new(bar_index, close, '', xloc = xloc.bar_index, color = color(na), style = label.style_label_left, size = size.tiny)
var label lbS2H = label.new(bar_index, close, '', xloc = xloc.bar_index, color = color(na), style = label.style_label_left, size = size.tiny)
var label lbS2L = label.new(bar_index, close, '', xloc = xloc.bar_index, color = color(na), style = label.style_label_left, size = size.tiny)

// @function  Обновить уровень: линия от левой границы обзора до правого края + подпись
f_setLevel(line ln, label lb, bool show, float v, string txt, color c) =>
    int xLvl = chart.left_visible_bar_time
    if show and not na(v) and not na(xLvl)
        ln.set_xy1(xLvl, v)
        ln.set_xy2(time, v)
        ln.set_color(color.new(c, 20))
        label.set_xy(lb, bar_index + 3, v)
        label.set_color(lb, color(na))
        label.set_text(lb, iLevLbl ? txt : '')
        label.set_textcolor(lb, c)
    else
        ln.set_color(na)
        label.set_text(lb, '')

// ---------------------------------------------------------------------------------------------------------------------
// KEY LEVELS
// ---------------------------------------------------------------------------------------------------------------------
if barstate.islast
    f_setLevel(lnPdH, lbPdH, eLevOn and iLevPd, levPdH, 'PDH', iLevColD)
    f_setLevel(lnPdL, lbPdL, eLevOn and iLevPd, levPdL, 'PDL', iLevColD)
    f_setLevel(lnPwH, lbPwH, eLevOn and iLevPw, levPwH, 'PWH', iLevColW)
    f_setLevel(lnPwL, lbPwL, eLevOn and iLevPw, levPwL, 'PWL', iLevColW)
    f_setLevel(lnS1H, lbS1H, eLevOn and iLevSw, levS1H, f_tfName(eLevTf1) + '·H', iLevColS1)
    f_setLevel(lnS1L, lbS1L, eLevOn and iLevSw, levS1L, f_tfName(eLevTf1) + '·L', iLevColS1)
    f_setLevel(lnS2H, lbS2H, eLevOn and iLevSw, levS2H, f_tfName(eLevTf2) + '·H', iLevColS2)
    f_setLevel(lnS2L, lbS2L, eLevOn and iLevSw, levS2L, f_tfName(eLevTf2) + '·L', iLevColS2)

// ---------------------------------------------------------------------------------------------------------------------
// POC / ПРОФИЛЬ ОБЪЁМА
//   1) дневной профиль (iPocTf) — для окна «POC дня», строки дашборда и условия конфлюенса;
//   2) профиль по последним N барам — гистограмма у ЛЕВОГО края, как на классическом профиле.
// ---------------------------------------------------------------------------------------------------------------------
var array<float> hist    = array.new<float>()
var float pocBase = na
var float pocStep = na
var float curPoc  = na
var float curVah  = na
var float curVal  = na
var float prevPoc = na
var float prevVah = na
var float prevVal = na

bool pocNewSess = ta.change(time(iPocTf)) != 0

if iPocOn and not na(volume)
    if pocNewSess
        prevPoc := curPoc
        prevVah := curVah
        prevVal := curVal
        array.clear(hist)
        pocBase := na
    if na(pocBase) or na(pocStep)
        pocStep := math.max(syminfo.mintick * 5, atrRef * iPocStepAtr)
        pocBase := low
        array.clear(hist)
        array.push(hist, 0.0)

    // Цена вышла за сетку, а бины кончились — укрупняем шаг вдвое и складываем соседние бины.
    if array.size(hist) >= iPocMaxBins
        bool outUp = int(math.floor((high - pocBase) / pocStep)) > array.size(hist) - 1
        bool outDn = int(math.floor((pocBase - low)  / pocStep)) > 0
        if outUp or outDn
            array<float> merged = array.new<float>()
            float accM = 0.0
            int   nOld = array.size(hist)
            for k = 0 to nOld - 1
                accM += array.get(hist, k)
                if (k % 2 == 1) or k == nOld - 1
                    array.push(merged, accM)
                    accM := 0.0
            hist    := merged
            pocStep := pocStep * 2

    int topIdx = int(math.floor((high - pocBase) / pocStep))
    while topIdx > array.size(hist) - 1 and array.size(hist) < iPocMaxBins
        array.push(hist, 0.0)
    int botIdx = int(math.floor((pocBase - low) / pocStep))
    if botIdx > 0
        int shiftN = int(math.min(botIdx, math.max(0, iPocMaxBins - array.size(hist))))
        if shiftN > 0
            for k = 1 to shiftN
                array.unshift(hist, 0.0)
            pocBase := pocBase - shiftN * pocStep

    int b0 = int(math.max(0, math.floor((low  - pocBase) / pocStep)))
    int b1 = int(math.min(array.size(hist) - 1, math.floor((high - pocBase) / pocStep)))
    if b1 >= b0
        float per = volume / (b1 - b0 + 1)
        for k = b0 to b1
            array.set(hist, k, array.get(hist, k) + per)

    float best = -1.0
    float tot  = 0.0
    int   bi   = 0
    for k = 0 to array.size(hist) - 1
        float hv = array.get(hist, k)
        tot += hv
        if hv > best
            best := hv
            bi   := k
    curPoc    := pocBase + (bi + 0.5) * pocStep

    float need  = tot * iPocVa / 100
    float acc   = best
    int   up    = bi
    int   dn    = bi
    int   guard = 0
    while acc < need and guard < 200
        guard += 1
        bool canUp = up < array.size(hist) - 1
        bool canDn = dn > 0
        if not canUp and not canDn
            break
        float uv = canUp ? array.get(hist, up + 1) : -1.0
        float dv = canDn ? array.get(hist, dn - 1) : -1.0
        if uv >= dv
            up  += 1
            acc += uv
        else
            dn  -= 1
            acc += dv
    curVah := pocBase + (up + 1) * pocStep
    curVal := pocBase + dn * pocStep

// ---------- буфер последних N баров (кольцевой, без сдвигов массива) ----------
var array<int>   rTm  = array.new<int>()
var array<float> rHi  = array.new<float>()
var array<float> rLo  = array.new<float>()
var array<float> rVol = array.new<float>()
var int   ringPos = 0
var float rPoc = na
var float rVah = na
var float rVal = na
var float rHvn1 = na
var float rHvn2 = na
var float rHvn3 = na

if iPocOn and iPocRangeOn
    if array.size(rHi) < iPocRangeBars
        array.push(rTm,  time)
        array.push(rHi,  high)
        array.push(rLo,  low)
        array.push(rVol, nz(volume))
    else
        int pRing = ringPos % iPocRangeBars
        array.set(rTm,  pRing, time)
        array.set(rHi,  pRing, high)
        array.set(rLo,  pRing, low)
        array.set(rVol, pRing, nz(volume))
    ringPos += 1

// ---------- объекты: линии на всю ширину + подписи у левого края ----------
var line lnPoc  = line.new(time, close, time + 1, close, xloc = xloc.bar_time, extend = extend.right, style = line.style_dashed, width = 2)
var line lnVah  = line.new(time, close, time + 1, close, xloc = xloc.bar_time, extend = extend.right, style = line.style_dotted, width = 1)
var line lnVal  = line.new(time, close, time + 1, close, xloc = xloc.bar_time, extend = extend.right, style = line.style_dotted, width = 1)
var line lnPocP = line.new(time, close, time + 1, close, xloc = xloc.bar_time, extend = extend.right, style = line.style_dashed, width = 1)
var line lnHvn1 = line.new(time, close, time + 1, close, xloc = xloc.bar_time, extend = extend.right, style = line.style_dotted, width = 1)
var line lnHvn2 = line.new(time, close, time + 1, close, xloc = xloc.bar_time, extend = extend.right, style = line.style_dotted, width = 1)
var line lnHvn3 = line.new(time, close, time + 1, close, xloc = xloc.bar_time, extend = extend.right, style = line.style_dotted, width = 1)

var label lbPoc  = label.new(na, na, '', xloc = xloc.bar_time, color = color(na), style = label.style_label_left, size = size.small)
var label lbVah  = label.new(na, na, '', xloc = xloc.bar_time, color = color(na), style = label.style_label_left, size = size.tiny)
var label lbVal  = label.new(na, na, '', xloc = xloc.bar_time, color = color(na), style = label.style_label_left, size = size.tiny)
var label lbPocP = label.new(na, na, '', xloc = xloc.bar_time, color = color(na), style = label.style_label_left, size = size.tiny)
var label lbHvn1 = label.new(na, na, '', xloc = xloc.bar_time, color = color(na), style = label.style_label_left, size = size.tiny)
var label lbHvn2 = label.new(na, na, '', xloc = xloc.bar_time, color = color(na), style = label.style_label_left, size = size.tiny)
var label lbHvn3 = label.new(na, na, '', xloc = xloc.bar_time, color = color(na), style = label.style_label_left, size = size.tiny)

// @function  Линия уровня от самого левого края графика (xloc.bar_time, тянется при прокрутке)
f_setLine(line ln, bool show, float v, color c) =>
    int xL = chart.left_visible_bar_time
    if show and not na(v) and not na(xL)
        ln.set_xy1(xL, v)
        ln.set_xy2(time, v)
        ln.set_color(color.new(c, 20))
    else
        ln.set_color(na)

// @function  Подпись у левого края (xloc.bar_time) — не мешает подписям EMA справа
f_pocLbl(label lb, bool show, float v, string txt, color c, int x) =>
    if show and not na(v) and not na(x) and iPocLbls
        label.set_xy(lb, x, v)
        label.set_color(lb, color(na))
        label.set_text(lb, txt)
        label.set_textcolor(lb, c)
    else
        label.set_text(lb, '')

// ---------- профиль объёма по последним N барам + отрисовка у левого края ----------
var array<box> profBoxes = array.new<box>()
int profWB = 0

if barstate.islast
    int barMs   = int(nz(time - time[1], timeframe.in_seconds() * 1000))
    int xLft    = chart.left_visible_bar_time
    int xRgt    = chart.right_visible_bar_time
    bool canProf = iPocOn and iPocRangeOn and iPocProf and array.size(rHi) >= 10 and not na(xLft) and not na(xRgt) and barMs > 0 and xRgt > xLft

    if canProf
        int   nB    = array.size(rHi)
        int   nbins = int(math.max(8, iPocProfBins))

        // границы профиля — по выбранным барам (по умолчанию только по видимым)
        float lo0 = na
        float hi0 = na
        for i = 0 to nB - 1
            int   tI  = array.get(rTm, i)
            float hiI = array.get(rHi, i)
            float loI = array.get(rLo, i)
            if (not iPocVisOnly or (not na(tI) and tI >= xLft)) and not na(hiI) and not na(loI)
                lo0 := na(lo0) ? loI : math.min(lo0, loI)
                hi0 := na(hi0) ? hiI : math.max(hi0, hiI)

        float stepR = (not na(lo0) and not na(hi0) and hi0 > lo0) ? (hi0 - lo0) / nbins : syminfo.mintick * nbins

        array<float> hR = array.new<float>()
        for k = 0 to nbins - 1
            array.push(hR, 0.0)

        for i = 0 to nB - 1
            int   tI  = array.get(rTm, i)
            float hiI = array.get(rHi, i)
            float loI = array.get(rLo, i)
            float vI  = array.get(rVol, i)
            bool  useI = not iPocVisOnly or (not na(tI) and tI >= xLft)
            if useI and not na(lo0) and not na(hiI) and not na(loI) and not na(vI)
                int q0 = int(math.max(0, math.floor((loI - lo0) / stepR)))
                int q1 = int(math.min(nbins - 1, math.floor((hiI - lo0) / stepR)))
                if q1 >= q0
                    float perR = vI / (q1 - q0 + 1)
                    for k = q0 to q1
                        array.set(hR, k, array.get(hR, k) + perR)

        // POC и суммарный объём
        float bestR = -1.0
        float totR  = 0.0
        int   biR   = 0
        for k = 0 to nbins - 1
            float hvR = array.get(hR, k)
            totR += hvR
            if hvR > bestR
                bestR := hvR
                biR   := k
        rPoc := lo0 + (biR + 0.5) * stepR

        // Value Area
        float needR  = totR * iPocVa / 100
        float accR   = bestR
        int   upR    = biR
        int   dnR    = biR
        int   guardR = 0
        while accR < needR and guardR < 400
            guardR += 1
            bool canUpR = upR < nbins - 1
            bool canDnR = dnR > 0
            if not canUpR and not canDnR
                break
            float uvR = canUpR ? array.get(hR, upR + 1) : -1.0
            float dvR = canDnR ? array.get(hR, dnR - 1) : -1.0
            if uvR >= dvR
                upR  += 1
                accR += uvR
            else
                dnR  -= 1
                accR += dvR
        rVah := lo0 + (upR + 1) * stepR
        rVal := lo0 + dnR * stepR

        // три крупнейших бина после POC — HVN
        float h1vR = -1.0
        float h2vR = -1.0
        float h3vR = -1.0
        float h1pR = na
        float h2pR = na
        float h3pR = na
        float thrR = bestR * iPocHvnPct / 100
        for k = 0 to nbins - 1
            float hvR = array.get(hR, k)
            if k != biR and hvR >= thrR
                float prR = lo0 + (k + 0.5) * stepR
                if hvR > h1vR
                    h3vR := h2vR
                    h3pR := h2pR
                    h2vR := h1vR
                    h2pR := h1pR
                    h1vR := hvR
                    h1pR := prR
                else if hvR > h2vR
                    h3vR := h2vR
                    h3pR := h2pR
                    h2vR := hvR
                    h2pR := prR
                else if hvR > h3vR
                    h3vR := hvR
                    h3pR := prR
        rHvn1 := h1pR
        rHvn2 := h2pR
        rHvn3 := h3pR

        // ширина профиля = доля окна, длина полосы = доля объёма
        int visBars = int(math.max(20, math.round((xRgt - xLft) * 1.0 / barMs)))
        profWB := int(math.max(6, math.round(visBars * iPocProfPct / 100.0)))
        int used = 0
        if bestR > 0
            for k = 0 to nbins - 1
                float vBin = array.get(hR, k)
                if vBin > 0
                    float rawBot = lo0 + k * stepR
                    float rawTop = rawBot + stepR
                    float gapB   = stepR * 0.16
                    float bTop   = rawTop - gapB
                    float bBot   = rawBot + gapB
                    float bMid   = math.avg(rawTop, rawBot)
                    int   wB     = int(math.max(1, math.round(profWB * vBin / bestR)))
                    int   xEnd   = xLft + wB * barMs
                    bool  isPoc  = k == biR
                    bool  inVaR  = not na(rVah) and not na(rVal) and rawBot >= rVal and rawTop <= rVah
                    color pcR    = isPoc ? iPocProfPocCol : (bMid >= close ? iPocProfUpCol : iPocProfDnCol)
                    int   paR    = isPoc ? 10 : (inVaR ? 45 : 72)
                    if used < array.size(profBoxes)
                        box pbOld = array.get(profBoxes, used)
                        pbOld.set_lefttop(xLft, bTop)
                        pbOld.set_rightbottom(xEnd, bBot)
                        pbOld.set_bgcolor(color.new(pcR, paR))
                        pbOld.set_border_color(color.new(pcR, math.min(100, paR + 20)))
                        pbOld.set_border_width(isPoc ? 2 : 1)
                    else
                        box pbNew = box.new(xLft, bTop, xEnd, bBot, xloc = xloc.bar_time,
                                            bgcolor = color.new(pcR, paR), border_color = color.new(pcR, math.min(100, paR + 20)),
                                            border_width = isPoc ? 2 : 1)
                        array.push(profBoxes, pbNew)
                    used += 1
        while array.size(profBoxes) > used
            box deadP = array.pop(profBoxes)
            if not na(deadP)
                deadP.delete()
    else if array.size(profBoxes) > 0
        while array.size(profBoxes) > 0
            box deadP2 = array.pop(profBoxes)
            if not na(deadP2)
                deadP2.delete()

    // линии и подписи: подписи — сразу справа от профиля
    int lblX = xLft + (iPocProf and iPocRangeOn ? profWB + 2 : 2) * barMs
    string txtPrevPoc = 'POC ' + (iPocTf == 'D' ? 'пред. дня' : f_tfName(iPocTf) + ' пред.')
    f_setLine(lnPoc,  iPocOn and iPocRangeOn and not na(rPoc),               rPoc,   iPocCol)
    f_setLine(lnVah,  iPocOn and iPocRangeOn and iPocVaOn and not na(rVah),  rVah,   iPocVaCol)
    f_setLine(lnVal,  iPocOn and iPocRangeOn and iPocVaOn and not na(rVal),  rVal,   iPocVaCol)
    f_setLine(lnPocP, iPocOn and iPocPrevOn and not na(prevPoc),             prevPoc, iPocPrevCol)
    f_setLine(lnHvn1, iPocOn and iPocRangeOn and iPocHvnOn and not na(rHvn1), rHvn1, iPocVaCol)
    f_setLine(lnHvn2, iPocOn and iPocRangeOn and iPocHvnOn and not na(rHvn2), rHvn2, iPocVaCol)
    f_setLine(lnHvn3, iPocOn and iPocRangeOn and iPocHvnOn and not na(rHvn3), rHvn3, iPocVaCol)
    f_pocLbl(lbPoc,  iPocOn and iPocRangeOn and not na(rPoc),               rPoc,   'POC ' + str.tostring(rPoc, format.mintick), iPocCol, lblX)
    f_pocLbl(lbVah,  iPocOn and iPocRangeOn and iPocVaOn and not na(rVah),  rVah,   'VAH ' + str.tostring(rVah, format.mintick), iPocVaCol, lblX)
    f_pocLbl(lbVal,  iPocOn and iPocRangeOn and iPocVaOn and not na(rVal),  rVal,   'VAL ' + str.tostring(rVal, format.mintick), iPocVaCol, lblX)
    f_pocLbl(lbPocP, iPocOn and iPocPrevOn and not na(prevPoc),             prevPoc, txtPrevPoc + ' ' + str.tostring(prevPoc, format.mintick), iPocPrevCol, lblX)
    f_pocLbl(lbHvn1, iPocOn and iPocRangeOn and iPocHvnOn and not na(rHvn1), rHvn1, 'HVN ' + str.tostring(rHvn1, format.mintick), iPocVaCol, lblX)
    f_pocLbl(lbHvn2, iPocOn and iPocRangeOn and iPocHvnOn and not na(rHvn2), rHvn2, 'HVN ' + str.tostring(rHvn2, format.mintick), iPocVaCol, lblX)
    f_pocLbl(lbHvn3, iPocOn and iPocRangeOn and iPocHvnOn and not na(rHvn3), rHvn3, 'HVN ' + str.tostring(rHvn3, format.mintick), iPocVaCol, lblX)

// ближайший ключевой уровень (для строки «Уровень»)
var array<float>  levVals  = array.new<float>()
var array<string> levNames = array.new<string>()
array.clear(levVals)
array.clear(levNames)
if eLevOn
    if iLevPd
        if not na(levPdH)
            levVals.push(levPdH)
            levNames.push('PDH')
        if not na(levPdL)
            levVals.push(levPdL)
            levNames.push('PDL')
    if iLevPw
        if not na(levPwH)
            levVals.push(levPwH)
            levNames.push('PWH')
        if not na(levPwL)
            levVals.push(levPwL)
            levNames.push('PWL')
    if iLevSw
        if not na(levS1H)
            levVals.push(levS1H)
            levNames.push(f_tfName(eLevTf1) + '·H')
        if not na(levS1L)
            levVals.push(levS1L)
            levNames.push(f_tfName(eLevTf1) + '·L')
        if not na(levS2H)
            levVals.push(levS2H)
            levNames.push(f_tfName(eLevTf2) + '·H')
        if not na(levS2L)
            levVals.push(levS2L)
            levNames.push(f_tfName(eLevTf2) + '·L')

float  nLevV = na
string nLevN = ''
if array.size(levVals) > 0
    for i = 0 to array.size(levVals) - 1
        float lv = array.get(levVals, i)
        if na(nLevV) or math.abs(lv - close) < math.abs(nLevV - close)
            nLevV := lv
            nLevN := array.get(levNames, i)

// ---------------------------------------------------------------------------------------------------------------------
// HELPERS
// ---------------------------------------------------------------------------------------------------------------------
// @function  Нарисовать линию + метку структуры
f_drawStructure(stState s, bool isBull, string tag, bool internal) =>
    color c   = isBull ? cBull : cBear
    float lvl = isBull ? s.hLvl : s.lLvl
    int   t0  = isBull ? s.hTime : s.lTime
    int   i0  = isBull ? s.hIdx : s.lIdx

    array<line>  qLines  = internal ? (isBull ? inBullLines : inBearLines) : (isBull ? swBullLines : swBearLines)
    array<label> qLabels = internal ? (isBull ? inBullLabel : inBearLabel) : (isBull ? swBullLabel : swBearLabel)

    if not na(lvl) and not na(t0)
        // короткий отрезок на уровне пробоя вместо линии во весь график
        int t1 = iExtendLines ? last_bar_time : time
        line ln = line.new(chart.point.new(t0, na, lvl), chart.point.new(t1, na, lvl), xloc = xloc.bar_time,
                           color = c, style = internal ? line.style_dashed : line.style_solid, width = 1)
        array.unshift(qLines, ln)

        if eStructLbl
            label lb = label.new(chart.point.new(na, int(math.round(0.5 * (i0 + bar_index))), lvl), tag, xloc = xloc.bar_index,
                                 color = color(na), textcolor = c,
                                 style = isBull ? label.style_label_down : label.style_label_up,
                                 size = internal ? size.tiny : size.small)
            array.unshift(qLabels, lb)

        // удаляем всё, что старше последних iKeepStruct
        while array.size(qLines) > iKeepStruct
            line deadLine = array.pop(qLines)
            if not na(deadLine)
                deadLine.delete()
        while array.size(qLabels) > iKeepStruct
            label deadLabel = array.pop(qLabels)
            if not na(deadLabel)
                deadLabel.delete()

// @function  Обновить состояние структуры по новым пивотам
f_updatePivots(stState s, float ph, float pl, int legs) =>
    if not na(ph)
        s.hLvl    := ph
        s.hIdx    := bar_index - legs
        s.hTime   := time[legs]
        // если цена уже находится за новым пивотом — уровень считается пройденным,
        // иначе получим поток "мгновенных BOS" без реального пробоя
        s.hBroken := close > ph
    if not na(pl)
        s.lLvl    := pl
        s.lIdx    := bar_index - legs
        s.lTime   := time[legs]
        s.lBroken := close < pl

// @function  Проверить пробой уровня и, если он подтверждён, обновить bias и нарисовать структуру
// @returns   [бычий пробой, медвежий пробой, тег бычьего, тег медвежьего]
f_checkBreaks(stState s, bool internal, float atrV) =>
    bool   bullBreak = false
    bool   bearBreak = false
    string bullTag   = ''
    string bearTag   = ''
    float  disp      = iDispMult * atrV
    bool   ready     = iConfirmed ? barstate.isconfirmed : true

    if ready and not na(s.hLvl) and not s.hBroken
        float src = iWickBreak ? high : close
        if src > s.hLvl + disp
            s.hBroken := true
            bullBreak := true
            bullTag   := s.bias == -1 ? 'CHoCH' : 'BOS'
            s.bias    := 1
            if internal ? iShowInt : iShowSwing
                f_drawStructure(s, true, bullTag, internal)

    if ready and not na(s.lLvl) and not s.lBroken
        float src = iWickBreak ? low : close
        if src < s.lLvl - disp
            s.lBroken := true
            bearBreak := true
            bearTag   := s.bias == 1 ? 'CHoCH' : 'BOS'
            s.bias    := -1
            if internal ? iShowInt : iShowSwing
                f_drawStructure(s, false, bearTag, internal)

    [bullBreak, bearBreak, bullTag, bearTag]

// @function  Найти последний противоположный бар перед импульсом (кандидат в OB)
// @returns   [top, bottom, time]
f_findOB(int fromIdx, bool bull, int maxScan) =>
    float top   = na
    float bot   = na
    int   tTime = na
    int   oIdx  = na
    int   from  = fromIdx
    int   depth = 0
    if not na(from)
        depth := int(math.min(bar_index - from, math.min(maxScan, bar_index - 1)))

    if depth > 0
        for i = 1 to depth
            bool isDown = close[i] < open[i]
            bool isUp   = close[i] > open[i]
            if (bull and isDown) or (not bull and isUp)
                top   := high[i]
                bot   := low[i]
                tTime := time[i]
                oIdx  := bar_index - i
                break

    [top, bot, tTime, oIdx]

// @function  Сколько условий конфлюенса вообще применимо при текущих настройках (для порога в %)
f_scoreMax() =>
    int m = 1
    if iShowFVG and array.size(fvgArr) > 0
        m += 1
    if eEmaOn and array.size(emaVals) > 0
        bool anyEma = false
        for i = 0 to array.size(emaVals) - 1
            if not na(array.get(emaVals, i))
                anyEma := true
        if anyEma
            m += 1
    if not na(swingSt.hLvl) and not na(swingSt.lLvl)
        m += 1
    if not na(curPoc)
        m += 1
    if array.size(levVals) > 0
        m += 1
    if iHtfTf != ''
        m += 1
    m

// @function  Оценка качества зоны по конфлюенсу (0..6):
//            1) перекрытие с активным FVG того же направления
//            2) близость к EMA старшего ТФ
//            3) правильная половина диапазона (дисконт для покупок / премиум для продаж)
//            4) POC текущего периода или попадание в Value Area
//            5) близость к ключевому уровню старшего ТФ (PDH/PDL/PWH/PWL/свинги)
//            6) структура не против сделки
f_zoneScore(bool bull, float top, float bot) =>
    int   score = 0
    int   mask  = 0
    float mid   = math.avg(top, bot)

    if array.size(fvgArr) > 0
        for i = array.size(fvgArr) - 1 to 0
            fvgZone z = array.get(fvgArr, i)
            if z.bias == (bull ? 1 : -1) and not z.mit
                if math.min(top, z.top) - math.max(bot, z.bot) > 0
                    score += 1
                    mask  += 1
                    break

    float nearEma = iAplusEmaAtr * atrRef
    if array.size(emaVals) > 0
        for i = 0 to array.size(emaVals) - 1
            float ev = array.get(emaVals, i)
            if not na(ev) and math.abs(mid - ev) <= nearEma
                score += 1
                mask  += 2
                break

    float hLs = swingSt.hLvl
    float lLs = swingSt.lLvl
    if not na(hLs) and not na(lLs) and hLs > lLs
        float eqLvl = math.avg(hLs, lLs)
        if (bull and mid < eqLvl) or (not bull and mid > eqLvl)
            score += 1
            mask  += 4

    if not na(curPoc)
        bool nearPoc = math.abs(mid - curPoc) <= iAplusPocAtr * atrRef
        bool inVa    = not na(curVah) and not na(curVal) and mid >= curVal and mid <= curVah
        if nearPoc or inVa
            score += 1
            mask  += 8

    if array.size(levVals) > 0
        bool hitLev = false
        for i = 0 to array.size(levVals) - 1
            float lv = array.get(levVals, i)
            if not na(lv) and math.abs(mid - lv) <= iAplusLevAtr * atrRef
                hitLev := true
                break
        if hitLev
            score += 1
            mask  += 16

    if (bull ? swingSt.bias >= 0 : swingSt.bias <= 0)
        score += 1
        mask  += 32

    if iHtfTf != '' and htfBias == (bull ? 1 : -1)
        score += 1
        mask  += 64

    [score, mask]

// @function  Создать зону OB (с дедупликацией, оценкой конфлюенса и лимитом)
f_storeOB(array<obZone> arr, int fromIdx, bool bull, color c, float minSizeAtp) =>
    [top, bot, tTime, oIdx] = f_findOB(fromIdx, bull, 60)
    bool ok = not na(top) and not na(bot) and not na(tTime) and not na(oIdx) and top > bot and (top - bot) >= minSizeAtp

    // Зона создаётся задним числом (пивот подтверждается на eSwingLegs баров позже),
    // поэтому сначала проверяем: не пробила ли её цена закрытием ПОСЛЕ её бара.
    // Иначе бокс появляется «мертвым» и удаляется на следующем же баре.
    if ok and eObSkipBroken
        int back = bar_index - oIdx
        if back >= 1
            for i = 0 to back - 1
                if bull ? close[i] < bot : close[i] > top
                    ok := false
                    break

    if ok and eObDedup and array.size(arr) > 0
        for i = array.size(arr) - 1 to 0
            obZone z = array.get(arr, i)
            if z.bias == (bull ? 1 : -1) and not na(z.top) and not na(z.bot)
                float ovl = math.min(top, z.top) - math.max(bot, z.bot)
                float ref = math.min(top - bot, z.top - z.bot)
                if ref > 0 and ovl / ref > 0.5
                    ok := false

    if ok
        [score, mask] = f_zoneScore(bull, top, bot)
        int   smax   = f_scoreMax()
        bool  strong = iAplus and smax > 0 and score * 100 >= smax * iAplusPct
        color zCol   = strong ? cStrong : c
        // простой box.new по bar_index + extend.right — самый совместимый способ отрисовки
        box b = box.new(oIdx, top, bar_index, bot, xloc = xloc.bar_index, extend = extend.right,
                        bgcolor = color.new(zCol, strong ? 72 : 86),
                        border_color = color.new(zCol, strong ? 15 : 50),
                        border_width = strong ? 2 : 1)
        array.unshift(arr, obZone.new(top, bot, bull ? 1 : -1, tTime, b, false, bar_index, strong, zCol, false, false, score, smax, mask))

    ok

// @function  Митигация зон OB + видимость (ближайшая поддержка и сопротивление видны всегда)
// @returns [бычий пробой, медвежий пробой, провалов поддержек, провалов сопротивлений, истекло]
f_mitigateOB(array<obZone> arr) =>
    bool bullBroke = false
    bool bearBroke = false
    int  lostSup   = 0
    int  lostRes   = 0
    int  expN      = 0
    int  removedN  = 0

    // ---- 1) отработанные зоны ----
    if array.size(arr) > 0
        for i = array.size(arr) - 1 to 0
            obZone z = array.get(arr, i)
            bool hit = false
            if not z.mit and z.born != bar_index
                if z.bias == 1
                    float src = eMitMode == 'Close' ? close : low
                    float lvl = eMitMode == '50%' ? math.avg(z.top, z.bot) : z.bot
                    hit := src <= lvl
                else
                    float src = eMitMode == 'Close' ? close : high
                    float lvl = eMitMode == '50%' ? math.avg(z.top, z.bot) : z.top
                    hit := src >= lvl
            if hit
                if z.bias == 1
                    bullBroke := true
                else
                    bearBroke := true
                if z.strong and z.touched and not z.done and iStats
                    if z.bias == 1
                        lostSup += 1
                    else
                        lostRes += 1
                z.done := true
                if iKeepMitigated
                    z.mit := true
                else
                    if not na(z.bx)
                        z.bx.delete()
                    arr.remove(i)
                    removedN += 1

    // ---- 2) видимость и цвет ----
    int visN = 0
    if array.size(arr) > 0
        for i = array.size(arr) - 1 to 0
            obZone z = array.get(arr, i)
            if not na(z.bx)
                float zDist   = math.abs(math.avg(z.top, z.bot) - close)
                bool  farZ    = eHideFar and zDist > eZoneAtr * atrRef
                // ближайшие iKeepNear зон КАЖДОЙ стороны видны всегда, даже если далеко
                bool  keepZ   = false
                if eHideFar and farZ
                    int closer = 0
                    for j = 0 to array.size(arr) - 1
                        obZone z2 = array.get(arr, j)
                        if j != i and not z2.mit and z2.bias == z.bias and not na(z2.top) and not na(z2.bot)
                            if math.abs(math.avg(z2.top, z2.bot) - close) < zDist
                                closer += 1
                    keepZ := closer < iKeepNear
                bool weakHide = eAplusOnly and iAplus and not z.strong
                if farZ and not keepZ
                    z.bx.set_bgcolor(na)
                    z.bx.set_border_color(na)
                else if z.mit
                    z.bx.set_bgcolor(color.new(color.gray, 93))
                    z.bx.set_border_color(color.new(color.gray, 88))
                    z.bx.set_border_style(line.style_dotted)
                else if weakHide
                    z.bx.set_bgcolor(na)
                    z.bx.set_border_color(na)
                else
                    z.bx.set_bgcolor(color.new(z.col, z.strong ? 72 : 86))
                    z.bx.set_border_color(color.new(z.col, z.strong ? 15 : 50))
                    z.bx.set_border_style(line.style_solid)
                    visN += 1

    // ---- 4) ограничиваем количество АКТИВНЫХ зон (отработанные остаются бледными) ----
    int active = 0
    if array.size(arr) > 0
        for i = array.size(arr) - 1 to 0
            obZone z = array.get(arr, i)
            if not z.mit
                active += 1
                if active > eMaxOB
                    if z.strong and z.touched and not z.done and iStats
                        expN += 1
                    z.done := true
                    if not na(z.bx)
                        z.bx.delete()
                    arr.remove(i)
                    removedN += 1

    while array.size(arr) > 40
        obZone deadOb = array.pop(arr)
        if not na(deadOb.bx)
            deadOb.bx.delete()
        removedN += 1

    [bullBroke, bearBroke, lostSup, lostRes, expN, removedN, visN]

// @function  Создать FVG (с дедупликацией и лимитом)
f_storeFVG(float bot, float top, int bias) =>
    bool dup = false
    if array.size(fvgArr) > 0
        for i = array.size(fvgArr) - 1 to 0
            fvgZone z = array.get(fvgArr, i)
            if z.bias == bias and math.abs(z.top - top) <= syminfo.mintick and math.abs(z.bot - bot) <= syminfo.mintick
                dup := true

    if not dup and top > bot
        color c = bias == 1 ? cBullFvg : cBearFvg
        box b = box.new(bar_index - 2, top, bar_index, bot, xloc = xloc.bar_index, extend = extend.right,
                        bgcolor = color.new(c, 84), border_color = color.new(c, 55))
        array.unshift(fvgArr, fvgZone.new(top, bot, bias, b, false, bar_index, c))

// @function  Митигация FVG
f_mitigateFVG() =>
    if array.size(fvgArr) > 0
        for i = array.size(fvgArr) - 1 to 0
            fvgZone z = array.get(fvgArr, i)
            if not z.mit and z.born != bar_index
                float half = math.avg(z.top, z.bot)
                bool hit = z.bias == 1 ? low <= (iFvgMit == '50%' ? half : z.bot) : high >= (iFvgMit == '50%' ? half : z.top)
                if hit
                    if iKeepMitigated
                        z.mit := true
                    else
                        if not na(z.bx)
                            z.bx.delete()
                        fvgArr.remove(i)
                        continue

            if not na(z.bx)
                float midF = math.avg(z.top, z.bot)
                bool  farF = eHideFar and math.abs(midF - close) > eZoneAtr * atrRef
                if farF
                    z.bx.set_bgcolor(na)
                    z.bx.set_border_color(na)
                else if z.mit
                    z.bx.set_bgcolor(color.new(color.gray, 94))
                    z.bx.set_border_color(color.new(color.gray, 90))
                    z.bx.set_border_style(line.style_dotted)
                else
                    z.bx.set_bgcolor(color.new(z.col, 84))
                    z.bx.set_border_color(color.new(z.col, 60))
                    z.bx.set_border_style(line.style_solid)

    int activeF = 0
    if array.size(fvgArr) > 0
        for i = array.size(fvgArr) - 1 to 0
            fvgZone z = array.get(fvgArr, i)
            if not z.mit
                activeF += 1
                if activeF > eMaxFvg
                    if not na(z.bx)
                        z.bx.delete()
                    fvgArr.remove(i)

    while array.size(fvgArr) > 30
        fvgZone deadF = array.pop(fvgArr)
        if not na(deadF.bx)
            deadF.bx.delete()

// @function  Расшифровка маски конфлюенса: какие именно условия совпали у A+ зоны
f_maskTxt(int m) =>
    array<string> nm = array.from('FVG', 'EMA', 'дисконт', 'POC', 'уровень', 'структура', 'HTF')
    string t = ''
    int    b = 1
    for i = 0 to 6
        if int(math.floor(m / b)) % 2 == 1
            t := t == '' ? array.get(nm, i) : t + ' · ' + array.get(nm, i)
        b := b * 2
    t

// @function  Ближайшая активная зона нужного направления: [расстояние, середина, A+, маска]
f_zoneNear(array<obZone> arr, int bias) =>
    float bd = na
    float bp = na
    bool  ba = false
    int   bm = 0
    if array.size(arr) > 0
        for i = 0 to array.size(arr) - 1
            obZone z = array.get(arr, i)
            if not z.mit and z.bias == bias and not na(z.top) and not na(z.bot)
                float p = math.avg(z.top, z.bot)
                float d = math.abs(p - close)
                if na(bd) or d < bd
                    bd := d
                    bp := p
                    ba := z.strong
                    bm := z.strong ? z.mask : 0
    [bd, bp, ba, bm]

// @function  Метка входа у A+ зоны: BUY у поддержки, SELL у сопротивления
//             okSide = эта сторона прошла фильтр по статистике/структуре
f_signal(int bias, float lvl, bool okSide, int score, int smax) =>
    if iSignalMarks and (okSide or iSignalWeak)
        color  c   = bias == 1 ? cBull : cBear
        string txt = (bias == 1 ? 'BUY ' : 'SELL ') + str.tostring(score) + '/' + str.tostring(smax)
        label lb = label.new(chart.point.new(na, bar_index, lvl), txt, xloc = xloc.bar_index,
                             color = color.new(#131722, okSide ? 0 : 15), textcolor = color.new(c, okSide ? 0 : 45),
                             style = bias == 1 ? label.style_label_up : label.style_label_down, size = size.tiny)
        array.unshift(sigLabels, lb)
        while array.size(sigLabels) > iSignalMax
            label deadSig = array.pop(sigLabels)
            if not na(deadSig)
                deadSig.delete()

// @function  Статистика A+ зон по каждой стороне:
//             касание -> отскок на need = успех | пробой зоны = провал | простой дольше iStatExpire = истекло
// @returns   [успехи поддержек, успехи сопротивлений, истекло, сигнал BUY, сигнал SELL, метка BUY, метка SELL]
f_updateStats(array<obZone> arr, float need, bool allowSup, bool allowRes) =>
    int  winSup = 0
    int  winRes = 0
    int  expN   = 0
    bool sigS   = false
    bool sigR   = false
    bool mrkS   = false
    bool mrkR   = false
    if array.size(arr) > 0
        for i = 0 to array.size(arr) - 1
            obZone z = array.get(arr, i)
            if z.strong and not z.mit and not z.done
                bool  inZone = z.bias == 1 ? low <= z.top : high >= z.bot
                if not z.touched
                    if inZone
                        z.touched := true
                        z.maxEx := high
                        z.minEx := low
                        if z.smax > 0 and z.score * 100 >= z.smax * iSignalMinPct
                            bool okSide = z.bias == 1 ? allowSup : allowRes
                            f_signal(z.bias, z.bias == 1 ? z.bot : z.top, okSide, z.score, z.smax)
                            if z.bias == 1
                                mrkS := true
                            else
                                mrkR := true
                            if okSide
                                if z.bias == 1
                                    sigS := true
                                else
                                    sigR := true
                else
                    // после касания запоминаем максимальный уход цены — иначе «отскок,
                    // случившийся на баре касания», терялся и win-rate был занижен
                    z.maxEx := math.max(nz(z.maxEx, high), high)
                    z.minEx := math.min(nz(z.minEx, low),  low)

                if z.touched
                    float lvlOff = z.bias == 1 ? z.top + need : z.bot - need
                    bool  bounced = z.bias == 1 ? (iStatClose ? close >= lvlOff : nz(z.maxEx, high) >= lvlOff) : (iStatClose ? close <= lvlOff : nz(z.minEx, low) <= lvlOff)
                    if bounced
                        z.done := true
                        if z.bias == 1
                            winSup += 1
                        else
                            winRes += 1
                    else if bar_index - z.born > iStatExpire
                        z.done := true
                        expN   += 1
    [winSup, winRes, expN, sigS, sigR, mrkS, mrkR]

// @function  Сколько A+ зон уже проверяется, но ещё не разрешилось (ждём отскок/пробой)
f_pending(array<obZone> arr) =>
    int n = 0
    if array.size(arr) > 0
        for i = 0 to array.size(arr) - 1
            obZone z = array.get(arr, i)
            if z.strong and z.touched and not z.done and not z.mit
                n += 1
    n

// @function  Проверить новый пивот на равенство с предыдущими (EQH / EQL) и отрисовать кластер
f_checkEqual(bool isHigh, float pLvl, int pIdx, int pTime, float tol) =>
    if not na(pLvl) and not na(pIdx)
        array<pivotPt> arr = isHigh ? pHiArr : pLoArr
        array<line>   ll  = isHigh ? eqhLines : eqlLines
        int n = int(math.min(array.size(arr), iEqScan))
        if n > 0
            for i = 0 to n - 1
                pivotPt p = array.get(arr, i)
                if not na(p.lvl) and math.abs(p.lvl - pLvl) <= tol
                    color c = isHigh ? cBear : cBull
                    float lvl = math.max(p.lvl, pLvl)
                    line ln = line.new(chart.point.new(p.tTime, na, lvl), chart.point.new(pTime, na, lvl), xloc = xloc.bar_time,
                             color = c, style = line.style_dotted, width = 2)
                    array.unshift(ll, ln)
                    if iShowEQLbl
                        label eqLb = label.new(chart.point.new(na, int(math.avg(p.bIdx, pIdx)), lvl), isHigh ? 'EQH' : 'EQL', xloc = xloc.bar_index,
                                  color = color(na), textcolor = c,
                                  style = isHigh ? label.style_label_down : label.style_label_up, size = size.tiny)
                        array.unshift(eqLabels, eqLb)
                        while array.size(eqLabels) > iMaxEQ
                            label deadEq = array.pop(eqLabels)
                            if not na(deadEq)
                                deadEq.delete()
                    while array.size(ll) > iMaxEQ
                        line oldEq = array.pop(ll)
                        if not na(oldEq)
                            oldEq.delete()
                    break
        array.unshift(arr, pivotPt.new(pLvl, pTime, pIdx))
        if array.size(arr) > 30
            array.pop(arr)

// @function  Подсветить снятие уровня EQH / EQL (sweep)
f_markSweeps() =>
    if array.size(eqhLines) > 0
        for i = 0 to array.size(eqhLines) - 1
            line ln = array.get(eqhLines, i)
            float y = ln.get_y1()
            if not na(y) and high > y and close < y
                ln.set_style(line.style_solid)
                ln.set_color(color.new(cBear, 40))
    if array.size(eqlLines) > 0
        for i = 0 to array.size(eqlLines) - 1
            line ln = array.get(eqlLines, i)
            float y = ln.get_y1()
            if not na(y) and low < y and close > y
                ln.set_style(line.style_solid)
                ln.set_color(color.new(cBull, 40))

// @function  Premium / Equilibrium / Discount от текущего dealing range
f_drawPD() =>
    float h = swingSt.hLvl
    float lo = swingSt.lLvl
    if not na(h) and not na(lo) and h > lo
        float rng = h - lo
        int   tH  = nz(swingSt.hTime, time)
        int   tL  = nz(swingSt.lTime, time)
        int   t0  = tH < tL ? tH : tL
        float eqL = math.avg(h, lo)

        box prem = pdPrem
        prem.set_top_left_point(    chart.point.new(t0, na, h))
        prem.set_bottom_right_point(chart.point.new(last_bar_time, na, h - 0.05 * rng))
        pdPremLb.set_point(chart.point.new(t0, na, h))

        box eqb = pdEq
        eqb.set_top_left_point(    chart.point.new(t0, na, eqL + 0.025 * rng))
        eqb.set_bottom_right_point(chart.point.new(last_bar_time, na, eqL - 0.025 * rng))
        pdEqLb.set_point(chart.point.new(t0, na, eqL))

        box dsc = pdDisc
        dsc.set_top_left_point(    chart.point.new(t0, na, lo + 0.05 * rng))
        dsc.set_bottom_right_point(chart.point.new(last_bar_time, na, lo))
        pdDiscLb.set_point(chart.point.new(t0, na, lo))

// ---------------------------------------------------------------------------------------------------------------------
// CALCULATIONS
// ---------------------------------------------------------------------------------------------------------------------
float phSwing = ta.pivothigh(high, eSwingLegs, eSwingLegs)
float plSwing = ta.pivotlow(low,  eSwingLegs, eSwingLegs)
float phInt   = ta.pivothigh(high, iIntLegs,   iIntLegs)
float plInt   = ta.pivotlow(low,   iIntLegs,   iIntLegs)

// ---------------------------------------------------------------------------------------------------------------------
// PIVOTS -> STATE
// ---------------------------------------------------------------------------------------------------------------------
f_updatePivots(swingSt, phSwing, plSwing, eSwingLegs)
f_updatePivots(intSt,   phInt,   plInt,   iIntLegs)

// метки HH/HL/LH/LL по swing-структуре
if iSwings and not na(phSwing)
    label.new(chart.point.new(na, bar_index - eSwingLegs, phSwing), phSwing > nz(prevHiLvl, phSwing) ? 'HH' : 'LH',
              xloc = xloc.bar_index, color = color(na), textcolor = cBear,
              style = label.style_label_down, size = size.tiny)
    prevHiLvl := phSwing
if iSwings and not na(plSwing)
    label.new(chart.point.new(na, bar_index - eSwingLegs, plSwing), plSwing < nz(prevLoLvl, plSwing) ? 'LL' : 'HL',
              xloc = xloc.bar_index, color = color(na), textcolor = cBull,
              style = label.style_label_up, size = size.tiny)
    prevLoLvl := plSwing

// Зоны поддержки/сопротивления появляются и на подтверждённом свинге,
// иначе в трендовых участках (где уровень пробит до подтверждения пивота) OB почти не создаются
if iOBOnPivot and iShowOB
    if not na(plSwing)
        if f_storeOB(swingOB, swingSt.lIdx, true,  cBullOB, eMinOBAtr * atrRef)
            statCreated += 1
    if not na(phSwing)
        if f_storeOB(swingOB, swingSt.hIdx, false, cBearOB, eMinOBAtr * atrRef)
            statCreated += 1

// EQH / EQL — по свингам структуры, а не по микро-пивотам
if iShowEQ
    f_checkEqual(true,  phSwing, bar_index - eSwingLegs, time[eSwingLegs], iEqTolAtr * atrRef)
    f_checkEqual(false, plSwing, bar_index - eSwingLegs, time[eSwingLegs], iEqTolAtr * atrRef)
    f_markSweeps()

// ---------------------------------------------------------------------------------------------------------------------
// STRUCTURE BREAKS (BOS / CHoCH)
// ---------------------------------------------------------------------------------------------------------------------
[swBull, swBear, swBullTag, swBearTag] = f_checkBreaks(swingSt, false, atrRef)
[intBull, intBear, intBullTag, intBearTag] = f_checkBreaks(intSt,  true,  atrRef)

// HTF-направление: 0 = фильтр выключен
bool htfOkBull = not iHtfFilter or htfBias >= 0
bool htfOkBear = not iHtfFilter or htfBias <= 0

// ---------------------------------------------------------------------------------------------------------------------
// ORDER BLOCKS
// ---------------------------------------------------------------------------------------------------------------------
// HTF-фильтр намеренно НЕ применяется к созданию зон: в тренде против HTF
// поддержки/сопротивления не появлялись вовсе. Фильтр остался только для алертов.
if swBull and iShowOB
    if f_storeOB(swingOB, swingSt.lIdx, true,  cBullOB, eMinOBAtr * atrRef)
        statCreated += 1
if swBear and iShowOB
    if f_storeOB(swingOB, swingSt.hIdx, false, cBearOB, eMinOBAtr * atrRef)
        statCreated += 1
if intBull and eShowIntOB
    if f_storeOB(intOB, intSt.lIdx, true,  cBullOB, eMinOBAtr * atrRef)
        statCreated += 1
if intBear and eShowIntOB
    if f_storeOB(intOB, intSt.hIdx, false, cBearOB, eMinOBAtr * atrRef)
        statCreated += 1

// статистика по сторонам + право ставить метку BUY/SELL
int   nSupS = statWinSup + statLossSup
int   nResS = statWinRes + statLossRes
float rateSup = nSupS > 0 ? 100.0 * statWinSup / nSupS : 0.0
float rateRes = nResS > 0 ? 100.0 * statWinRes / nResS : 0.0

bool okStatSup = not iStats or not iSignalGate or (nSupS >= iSignalMinN and rateSup >= iSignalMinRate)
bool okStatRes = not iStats or not iSignalGate or (nResS >= iSignalMinN and rateRes >= iSignalMinRate)
bool okDirSup  = not iSignalStruct or swingSt.bias >= 0
bool okDirRes  = not iSignalStruct or swingSt.bias <= 0
bool coolSup   = bar_index - lastSigBarSup >= iSignalCool
bool coolRes   = bar_index - lastSigBarRes >= iSignalCool
bool allowSup  = okStatSup and okDirSup and coolSup
bool allowRes  = okStatRes and okDirRes and coolRes

bool sigBuy  = false
bool sigSell = false

[winS1, winR1, exp1, sg1, sr1, mk1s, mk1r] = f_updateStats(swingOB, iStatAtr * atrRef, allowSup, allowRes)
[winS2, winR2, exp2, sg2, sr2, mk2s, mk2r] = f_updateStats(intOB,   iStatAtr * atrRef, allowSup, allowRes)

// пауза считается по любой поставленной метке, включая «слабые»
if mk1s or mk2s
    lastSigBarSup := bar_index
if mk1r or mk2r
    lastSigBarRes := bar_index

if iStats
    statWinSup += winS1 + winS2
    statWinRes += winR1 + winR2
    statExp    += exp1 + exp2

sigBuy  := sg1 or sg2
sigSell := sr1 or sr2

[obBrokeBull1, obBrokeBear1, obLs1, obLr1, obLe1, obRem1, obVis1] = f_mitigateOB(swingOB)
[obBrokeBull2, obBrokeBear2, obLs2, obLr2, obLe2, obRem2, obVis2] = f_mitigateOB(intOB)

statRemoved += obRem1 + obRem2
statVisible := obVis1 + obVis2

if iStats
    statLossSup += obLs1 + obLs2
    statLossRes += obLr1 + obLr2
    statExp     += obLe1 + obLe2

bool zoneBrokeBull = obBrokeBull1 or obBrokeBull2
bool zoneBrokeBear = obBrokeBear1 or obBrokeBear2

// ближайшие активные зоны (для дашборда и алертов)
[dnSup1, prSup1, apSup1, mkSup1] = f_zoneNear(swingOB,  1)
[dnSup2, prSup2, apSup2, mkSup2] = f_zoneNear(intOB,    1)
[dnRes1, prRes1, apRes1, mkRes1] = f_zoneNear(swingOB, -1)
[dnRes2, prRes2, apRes2, mkRes2] = f_zoneNear(intOB,   -1)

float dnSup = na
float prSup = na
bool  apSup = false
int   mkSup = 0
float dnRes = na
float prRes = na
bool  apRes = false
int   mkRes = 0

if not na(dnSup1)
    dnSup := dnSup1
    prSup := prSup1
    apSup := apSup1
    mkSup := mkSup1
if not na(dnSup2) and (na(dnSup) or dnSup2 < dnSup)
    dnSup := dnSup2
    prSup := prSup2
    apSup := apSup2
    mkSup := mkSup2
if not na(dnRes1)
    dnRes := dnRes1
    prRes := prRes1
    apRes := apRes1
    mkRes := mkRes1
if not na(dnRes2) and (na(dnRes) or dnRes2 < dnRes)
    dnRes := dnRes2
    prRes := prRes2
    apRes := apRes2
    mkRes := mkRes2

// ---------------------------------------------------------------------------------------------------------------------
// FAIR VALUE GAPS
// ---------------------------------------------------------------------------------------------------------------------
bool fvgReady = not iConfirmed or barstate.isconfirmed

if iShowFVG and fvgReady and bar_index > 2
    float minGap = iFvgMinAtr * atrRef
    if low > high[2] and close > high[2] and (low - high[2]) >= minGap
        f_storeFVG(high[2], low, 1)
    if high < low[2] and close < low[2] and (low[2] - high) >= minGap
        f_storeFVG(high, low[2], -1)

f_mitigateFVG()

// ---------------------------------------------------------------------------------------------------------------------
// PREMIUM / DISCOUNT
// ---------------------------------------------------------------------------------------------------------------------
if eShowPD
    f_drawPD()

// ---------------------------------------------------------------------------------------------------------------------
// DASHBOARD — контекст одним взглядом (правый верхний угол)
// ---------------------------------------------------------------------------------------------------------------------
var table dash = table.new(position.top_right, 2, 14, bgcolor = color.new(#131722, 10), border_width = 1, border_color = color.new(color.gray, 80), frame_width = 1, frame_color = color.new(color.gray, 70))

// @function  Строка дашборда: название слева, значение справа
f_dashRow(int row, string name, string val, color c) =>
    table.cell(dash, 0, row, name, text_color = color.new(color.gray, 15), text_size = size.tiny, bgcolor = color.new(#131722, 10), text_halign = text.align_left)
    table.cell(dash, 1, row, val,  text_color = c, text_size = size.tiny, bgcolor = color.new(#131722, 10), text_halign = text.align_right)

if iDash and barstate.islast
    string sBias = swingSt.bias == 1 ? '▲ бычья' : (swingSt.bias == -1 ? '▼ медвежья' : '— нет')
    color  cBias = swingSt.bias == 1 ? cBull : (swingSt.bias == -1 ? cBear : color.gray)
    float  hLz  = swingSt.hLvl
    float  lLz  = swingSt.lLvl
    float  rng  = not na(hLz) and not na(lLz) and hLz > lLz ? (close - lLz) / (hLz - lLz) : na
    string sRng = na(rng) ? '—' : (rng > 0.6 ? 'премиум ' : (rng < 0.4 ? 'дисконт ' : 'равновесие ')) + str.tostring(rng * 100, '#') + '%'
    color  cRng = na(rng) ? color.gray : (rng > 0.6 ? cBear : (rng < 0.4 ? cBull : color.gray))
    string sSup = na(prSup) ? '—' : str.tostring(prSup, format.mintick) + ' · ' + str.tostring(dnSup / atrRef, '#.#') + ' ATR' + (apSup ? ' · A+' : '')
    string sRes = na(prRes) ? '—' : str.tostring(prRes, format.mintick) + ' · ' + str.tostring(dnRes / atrRef, '#.#') + ' ATR' + (apRes ? ' · A+' : '')
    string sLvl = na(nLevV) ? '—' : nLevN + ' ' + str.tostring(nLevV, format.mintick) + ' · ' + str.tostring(math.abs(nLevV - close) / atrRef, '#.#') + ' ATR'
    int    nStatS = statWinSup + statLossSup
    int    nStatR = statWinRes + statLossRes
    string sStatS = nStatS > 0 ? str.tostring(statWinSup) + '/' + str.tostring(statLossSup) + ' · ' + str.tostring(100.0 * statWinSup / nStatS, '#') + '%' + (nStatS < iSignalMinN ? ' · n мал' : '') : '—'
    string sStatR = nStatR > 0 ? str.tostring(statWinRes) + '/' + str.tostring(statLossRes) + ' · ' + str.tostring(100.0 * statWinRes / nStatR, '#') + '%' + (nStatR < iSignalMinN ? ' · n мал' : '') : '—'
    int    nPend  = f_pending(swingOB) + f_pending(intOB)
    string sPend  = str.tostring(nPend) + ' в работе · ' + str.tostring(statExp) + ' истекло'
    string sZones = str.tostring(array.size(swingOB)) + '+' + str.tostring(array.size(intOB)) + ' OB · ' + str.tostring(array.size(fvgArr)) + ' FVG'
    string sLife  = 'видно ' + str.tostring(statVisible) + ' · ' + str.tostring(statCreated) + ' создано / ' + str.tostring(statRemoved) + ' снято'
    string sPoc   = na(curPoc) ? '—' : str.tostring(curPoc, format.mintick) + ' · ' + str.tostring(math.abs(curPoc - close) / atrRef, '#.#') + ' ATR' + (na(curVah) ? '' : ' · VA ' + str.tostring(curVal, format.mintick) + '–' + str.tostring(curVah, format.mintick))
    int    mkNear = 0
    float  dNear  = na
    if apSup and not na(dnSup)
        mkNear := mkSup
        dNear  := dnSup
    if apRes and not na(dnRes) and (na(dNear) or dnRes < dNear)
        mkNear := mkRes
        dNear  := dnRes
    string sMask = mkNear > 0 ? f_maskTxt(mkNear) : '—'
    string sHtf = iHtfTf == '' ? 'выкл' : (htfBias == 1 ? '▲ выше EMA' : '▼ ниже EMA')
    color  cHtf = iHtfTf == '' ? color.gray : (htfBias == 1 ? cBull : cBear)

    table.cell(dash, 0, 0, 'SMC Pro', text_color = #e8eaed, text_size = size.small, bgcolor = color.new(#131722, 10), text_halign = text.align_left)
    table.cell(dash, 1, 0, timeframe.period, text_color = color.new(color.gray, 10), text_size = size.small, bgcolor = color.new(#131722, 10), text_halign = text.align_right)
    f_dashRow(1, 'Структура',        sBias,  cBias)
    f_dashRow(2, 'HTF',              sHtf,   cHtf)
    f_dashRow(3, 'Диапазон',         sRng,   cRng)
    f_dashRow(4, 'Поддержка',        sSup,   apSup ? cStrong : color.new(color.gray, 5))
    f_dashRow(5, 'Сопротивление',    sRes,   apRes ? cStrong : color.new(color.gray, 5))
    f_dashRow(6, 'Уровень',          sLvl,   color.new(color.gray, 5))
    f_dashRow(7, 'A+ покупки',  sStatS, nStatS > 0 ? (statWinSup >= statLossSup ? cBull : cBear) : color.gray)
    f_dashRow(8, 'A+ продажи',  sStatR, nStatR > 0 ? (statWinRes >= statLossRes ? cBull : cBear) : color.gray)
    f_dashRow(9, 'Проверка',    sPend,  color.new(color.gray, 5))
    f_dashRow(10, 'POC дня',    sPoc,   na(curPoc) ? color.gray : color.new(iPocCol, 20))
    f_dashRow(11, 'A+ условия', sMask,  color.new(cStrong, 20))
    f_dashRow(12, 'Активных',   sZones, color.new(color.gray, 5))
    f_dashRow(13, 'Жизнь зон',  sLife,  statVisible > 0 ? color.new(color.gray, 5) : cBear)

// ---------------------------------------------------------------------------------------------------------------------
// ALERTS
// ---------------------------------------------------------------------------------------------------------------------
string msg = ''
if swBull and htfOkBull
    msg += 'Swing ' + swBullTag + ' bullish @ ' + str.tostring(close, format.mintick) + '\n'
if swBear and htfOkBear
    msg += 'Swing ' + swBearTag + ' bearish @ ' + str.tostring(close, format.mintick) + '\n'
if intBull and htfOkBull
    msg += 'Internal ' + intBullTag + ' bullish @ ' + str.tostring(close, format.mintick) + '\n'
if intBear and htfOkBear
    msg += 'Internal ' + intBearTag + ' bearish @ ' + str.tostring(close, format.mintick) + '\n'

if iAlerts and msg != ''
    alert(msg, alert.freq_once_per_bar_close)

// подход к A+ зоне: цена ближе iAlertNearAtr*ATR к ближайшей A+ зоне своего направления
bool nearSupA = iAlertNear and apSup and not na(dnSup) and dnSup <= iAlertNearAtr * atrRef
bool nearResA = iAlertNear and apRes and not na(dnRes) and dnRes <= iAlertNearAtr * atrRef

if nearSupA and bar_index - lastZoneAlert >= iAlertCool
    lastZoneAlert := bar_index
    alert('SMC: подход к A+ поддержке ' + str.tostring(prSup, format.mintick) + ' (' + str.tostring(dnSup / atrRef, '#.##') + ' ATR)', alert.freq_once_per_bar_close)
if nearResA and bar_index - lastZoneAlert >= iAlertCool
    lastZoneAlert := bar_index
    alert('SMC: подход к A+ сопротивлению ' + str.tostring(prRes, format.mintick) + ' (' + str.tostring(dnRes / atrRef, '#.##') + ' ATR)', alert.freq_once_per_bar_close)
if iAlertBreak and zoneBrokeBull and bar_index - lastZoneAlert >= iAlertCool
    lastZoneAlert := bar_index
    alert('SMC: поддержка сломана @ ' + str.tostring(close, format.mintick), alert.freq_once_per_bar_close)
if iAlertBreak and zoneBrokeBear and bar_index - lastZoneAlert >= iAlertCool
    lastZoneAlert := bar_index
    alert('SMC: сопротивление сломано @ ' + str.tostring(close, format.mintick), alert.freq_once_per_bar_close)

// сигналы входа по статистике (пункт 7)
if iAlerts and sigBuy
    alert('SMC: BUY у A+ поддержки @ ' + str.tostring(close, format.mintick), alert.freq_once_per_bar_close)
if iAlerts and sigSell
    alert('SMC: SELL у A+ сопротивления @ ' + str.tostring(close, format.mintick), alert.freq_once_per_bar_close)

alertcondition(swBull and htfOkBull, 'Swing bullish break', 'Swing bullish BOS/CHoCH')
alertcondition(swBear and htfOkBear, 'Swing bearish break', 'Swing bearish BOS/CHoCH')
alertcondition(intBull and htfOkBull, 'Internal bullish break', 'Internal bullish BOS/CHoCH')
alertcondition(intBear and htfOkBear, 'Internal bearish break', 'Internal bearish BOS/CHoCH')
alertcondition(nearSupA and not nearSupA[1], 'SMC: подход к A+ поддержке',   'Цена подошла к A+ зоне поддержки (только на входе в зону)')
alertcondition(nearResA and not nearResA[1], 'SMC: подход к A+ сопротивлению', 'Цена подошла к A+ зоне сопротивления (только на входе в зону)')
alertcondition(zoneBrokeBull, 'SMC: поддержка сломана',  'Бычья зона пробита (поддержка сломана)')
alertcondition(zoneBrokeBear, 'SMC: сопротивление сломано', 'Медвежья зона пробита (сопротивление сломано)')
alertcondition(sigBuy,  'SMC: сигнал BUY',  'Цена вошла в A+ зону поддержки (статистика стороны выше порога)')
alertcondition(sigSell, 'SMC: сигнал SELL', 'Цена вошла в A+ зону сопротивления (статистика стороны выше порога)')

// ---------------------------------------------------------------------------------------------------------------------
// PLOTS (цвет свечей считается ПОСЛЕ структуры — без отставания на бар)
// ---------------------------------------------------------------------------------------------------------------------
// EMA — ровные непрерывные линии
plot(eEmaOn and iTfOn1 and pA1 > 0 ? emaA1 : na, 'EMA T1a', color = clrA1, style = plot.style_line, linewidth = iEmaWidth)
plot(eEmaOn and iTfOn1 and pB1 > 0 ? emaA2 : na, 'EMA T1b', color = clrA2, style = plot.style_line, linewidth = iEmaWidth)
plot(eEmaOn and iTfOn1 and pC1 > 0 ? emaA3 : na, 'EMA T1c', color = clrA3, style = plot.style_line, linewidth = iEmaWidth)
plot(eEmaOn and iTfOn2 and pA2 > 0 ? emaB1 : na, 'EMA T2a', color = clrB1, style = plot.style_line, linewidth = iEmaWidth)
plot(eEmaOn and iTfOn2 and pB2 > 0 ? emaB2 : na, 'EMA T2b', color = clrB2, style = plot.style_line, linewidth = iEmaWidth)
plot(eEmaOn and iTfOn2 and pC2 > 0 ? emaB3 : na, 'EMA T2c', color = clrB3, style = plot.style_line, linewidth = iEmaWidth)
plot(eEmaOn and iTfOn3 and pA3 > 0 ? emaC1 : na, 'EMA T3a', color = clrC1, style = plot.style_line, linewidth = iEmaWidth)
plot(eEmaOn and iTfOn3 and pB3 > 0 ? emaC2 : na, 'EMA T3b', color = clrC2, style = plot.style_line, linewidth = iEmaWidth)
plot(eEmaOn and iTfOn3 and pC3 > 0 ? emaC3 : na, 'EMA T3c', color = clrC3, style = plot.style_line, linewidth = iEmaWidth)
plot(eEmaOn and iTfOn4 and pA4 > 0 ? emaD1 : na, 'EMA T4a', color = clrD1, style = plot.style_line, linewidth = iEmaWidth)
plot(eEmaOn and iTfOn4 and pB4 > 0 ? emaD2 : na, 'EMA T4b', color = clrD2, style = plot.style_line, linewidth = iEmaWidth)
plot(eEmaOn and iTfOn4 and pC4 > 0 ? emaD3 : na, 'EMA T4c', color = clrD3, style = plot.style_line, linewidth = iEmaWidth)
// подписи у правого края: 1H·50, 1D·200 и т.п.
if barstate.islast
    int rt = last_bar_time + 20 * nz(time - time[1], timeframe.in_seconds() * 1000)
    f_setEmaLabel(lbA1, eEmaOn and iEmaLabels and iTfOn1 and pA1 > 0, emaA1, rt, f_tfName(eTf1) + '·' + str.tostring(pA1), iColA1)
    f_setEmaLabel(lbA2, eEmaOn and iEmaLabels and iTfOn1 and pB1 > 0, emaA2, rt, f_tfName(eTf1) + '·' + str.tostring(pB1), iColB1)
    f_setEmaLabel(lbA3, eEmaOn and iEmaLabels and iTfOn1 and pC1 > 0, emaA3, rt, f_tfName(eTf1) + '·' + str.tostring(pC1), iColC1)
    f_setEmaLabel(lbB1, eEmaOn and iEmaLabels and iTfOn2 and pA2 > 0, emaB1, rt, f_tfName(eTf2) + '·' + str.tostring(pA2), iColA2)
    f_setEmaLabel(lbB2, eEmaOn and iEmaLabels and iTfOn2 and pB2 > 0, emaB2, rt, f_tfName(eTf2) + '·' + str.tostring(pB2), iColB2)
    f_setEmaLabel(lbB3, eEmaOn and iEmaLabels and iTfOn2 and pC2 > 0, emaB3, rt, f_tfName(eTf2) + '·' + str.tostring(pC2), iColC2)
    f_setEmaLabel(lbC1, eEmaOn and iEmaLabels and iTfOn3 and pA3 > 0, emaC1, rt, f_tfName(eTf3) + '·' + str.tostring(pA3), iColA3)
    f_setEmaLabel(lbC2, eEmaOn and iEmaLabels and iTfOn3 and pB3 > 0, emaC2, rt, f_tfName(eTf3) + '·' + str.tostring(pB3), iColB3)
    f_setEmaLabel(lbC3, eEmaOn and iEmaLabels and iTfOn3 and pC3 > 0, emaC3, rt, f_tfName(eTf3) + '·' + str.tostring(pC3), iColC3)
    f_setEmaLabel(lbD1, eEmaOn and iEmaLabels and iTfOn4 and pA4 > 0, emaD1, rt, f_tfName(eTf4) + '·' + str.tostring(pA4), iColA4)
    f_setEmaLabel(lbD2, eEmaOn and iEmaLabels and iTfOn4 and pB4 > 0, emaD2, rt, f_tfName(eTf4) + '·' + str.tostring(pB4), iColB4)
    f_setEmaLabel(lbD3, eEmaOn and iEmaLabels and iTfOn4 and pC4 > 0, emaD3, rt, f_tfName(eTf4) + '·' + str.tostring(pC4), iColC4)
color candleCol = intSt.bias == 1 ? cBull : (intSt.bias == -1 ? cBear : color.new(color.gray, 60))
plotcandle(iColorCandles ? open : na, high, low, close, color = candleCol, wickcolor = candleCol, bordercolor = candleCol)
