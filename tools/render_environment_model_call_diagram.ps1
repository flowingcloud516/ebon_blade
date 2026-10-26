param(
    [string]$OutputPath = "design/images/environment-model-class-map-v2.png"
)

Add-Type -AssemblyName System.Drawing
$ErrorActionPreference = "Stop"

$width = 2200
$height = 1540
$bitmap = New-Object System.Drawing.Bitmap($width, $height)
$graphics = [System.Drawing.Graphics]::FromImage($bitmap)
$graphics.SmoothingMode = [System.Drawing.Drawing2D.SmoothingMode]::AntiAlias
$graphics.TextRenderingHint = [System.Drawing.Text.TextRenderingHint]::ClearTypeGridFit
$graphics.Clear([System.Drawing.Color]::FromArgb(248, 250, 252))

$fontName = "Microsoft YaHei UI"
$titleFont = New-Object System.Drawing.Font($fontName, 24, [System.Drawing.FontStyle]::Bold)
$laneFont = New-Object System.Drawing.Font($fontName, 16, [System.Drawing.FontStyle]::Bold)
$boxTitleFont = New-Object System.Drawing.Font($fontName, 13, [System.Drawing.FontStyle]::Bold)
$rowFont = New-Object System.Drawing.Font($fontName, 10, [System.Drawing.FontStyle]::Regular)
$rowBoldFont = New-Object System.Drawing.Font($fontName, 10, [System.Drawing.FontStyle]::Bold)
$smallFont = New-Object System.Drawing.Font($fontName, 9, [System.Drawing.FontStyle]::Regular)

$ink = [System.Drawing.Color]::FromArgb(30, 41, 59)
$muted = [System.Drawing.Color]::FromArgb(71, 85, 105)
$line = [System.Drawing.Color]::FromArgb(100, 116, 139)
$boxFill = [System.Drawing.Color]::White
$boxBorder = [System.Drawing.Color]::FromArgb(100, 116, 139)
$dataFill = [System.Drawing.Color]::FromArgb(219, 234, 254)
$dataInk = [System.Drawing.Color]::FromArgb(30, 64, 175)
$callFill = [System.Drawing.Color]::FromArgb(255, 237, 213)
$callInk = [System.Drawing.Color]::FromArgb(154, 52, 18)
$implFill = [System.Drawing.Color]::FromArgb(220, 252, 231)
$implInk = [System.Drawing.Color]::FromArgb(21, 128, 61)
$neutralFill = [System.Drawing.Color]::FromArgb(241, 245, 249)
$abstractBorder = [System.Drawing.Color]::FromArgb(217, 119, 6)
$frameworkBorder = [System.Drawing.Color]::FromArgb(37, 99, 235)

function Brush([System.Drawing.Color]$color) {
    New-Object System.Drawing.SolidBrush($color)
}

function Draw-Text($g, $text, $font, $color, $x, $y, $w, $h, $alignment = "Near") {
    $b = Brush $color
    $f = New-Object System.Drawing.StringFormat
    $f.Alignment = [System.Drawing.StringAlignment]::$alignment
    $f.LineAlignment = [System.Drawing.StringAlignment]::Center
    $f.Trimming = [System.Drawing.StringTrimming]::EllipsisCharacter
    $g.DrawString($text, $font, $b, (New-Object System.Drawing.RectangleF($x, $y, $w, $h)), $f)
    $f.Dispose()
    $b.Dispose()
}

function Draw-RoundedRect($g, $x, $y, $w, $h, $fill, $border, $borderWidth = 2) {
    $r = 10
    $d = $r * 2
    $path = New-Object System.Drawing.Drawing2D.GraphicsPath
    $path.AddArc($x, $y, $d, $d, 180, 90)
    $path.AddArc($x + $w - $d, $y, $d, $d, 270, 90)
    $path.AddArc($x + $w - $d, $y + $h - $d, $d, $d, 0, 90)
    $path.AddArc($x, $y + $h - $d, $d, $d, 90, 90)
    $path.CloseFigure()
    $b = Brush $fill
    $p = New-Object System.Drawing.Pen($border, $borderWidth)
    $g.FillPath($b, $path)
    $g.DrawPath($p, $path)
    $b.Dispose(); $p.Dispose(); $path.Dispose()
}

function Draw-ContractBox($g, $x, $y, $w, $h, $title, $subtitle, $rows, $border = $boxBorder) {
    Draw-RoundedRect $g $x $y $w $h $boxFill $border 2
    Draw-Text $g $title $boxTitleFont $ink ($x + 10) ($y + 5) ($w - 20) 27 "Center"
    Draw-Text $g $subtitle $smallFont $muted ($x + 10) ($y + 31) ($w - 20) 22 "Center"
    $p = New-Object System.Drawing.Pen($border, 1)
    $g.DrawLine($p, $x + 10, $y + 57, $x + $w - 10, $y + 57)
    $p.Dispose()
    $rowY = $y + 64
    foreach ($row in $rows) {
        $parts = $row -split '\|', 2
        $kind = $parts[0]
        $text = $parts[1]
        switch ($kind) {
            "DATA" { $fill = $dataFill; $color = $dataInk; $prefix = "DATA  "; $font = $rowFont }
            "CALL" { $fill = $callFill; $color = $callInk; $prefix = "CALL  "; $font = $rowBoldFont }
            "IMPL" { $fill = $implFill; $color = $implInk; $prefix = "IMPL  "; $font = $rowBoldFont }
            default { $fill = $neutralFill; $color = $ink; $prefix = ""; $font = $rowFont }
        }
        $b = Brush $fill
        $g.FillRectangle($b, $x + 8, $rowY, $w - 16, 25)
        $b.Dispose()
        Draw-Text $g ($prefix + $text) $font $color ($x + 15) $rowY ($w - 30) 25
        $rowY += 29
    }
}

function Draw-Arrow($g, $x1, $y1, $x2, $y2, $label) {
    $p = New-Object System.Drawing.Pen($line, 2)
    $g.DrawLine($p, $x1, $y1, $x2, $y2)
    $angle = [Math]::Atan2($y2 - $y1, $x2 - $x1)
    $size = 11
    $points = [System.Drawing.PointF[]]@(
        [System.Drawing.PointF]::new([single]$x2, [single]$y2),
        [System.Drawing.PointF]::new([single]($x2 - $size * [Math]::Cos($angle - [Math]::PI / 6)), [single]($y2 - $size * [Math]::Sin($angle - [Math]::PI / 6))),
        [System.Drawing.PointF]::new([single]($x2 - $size * [Math]::Cos($angle + [Math]::PI / 6)), [single]($y2 - $size * [Math]::Sin($angle + [Math]::PI / 6)))
    )
    $b = Brush $line
    $g.FillPolygon($b, $points)
    $b.Dispose(); $p.Dispose()
    if ($label) {
        $mx = [int](($x1 + $x2) / 2) - 75
        $my = [int](($y1 + $y2) / 2) - 25
        Draw-Text $g $label $smallFont $muted $mx $my 150 22 "Center"
    }
}

function Draw-VerticalArrow($g, $x, $y1, $y2, $label) {
    Draw-Arrow $g $x $y1 $x $y2 $label
}

# Header and notation
Draw-Text $graphics "Environment Model 调用方向与类契约（V2）" $titleFont $ink 40 15 2120 45 "Center"
Draw-Text $graphics "括号内是外部传入参数；→ 后是类返回值。DATA是类提供/持有的数据，CALL是外部或框架调用的方法，IMPL是具体env_model必须实现的方法。" $rowFont $muted 40 60 2120 30 "Center"

Draw-Text $graphics "入口与环境扩展契约" $laneFont $ink 45 105 500 32

# Entry and extension lane
Draw-ContractBox $graphics 45 150 280 180 "UI / CLI / API" "框架外部调用者" @(
    "DATA|effective_config",
    "CALL|initialize(config, connector_factory)",
    "CALL|finish_run()"
) $boxBorder

Draw-ContractBox $graphics 380 135 430 220 "EnvironmentControlService" "框架公共门面；具体Model不得覆盖" @(
    "DATA|registry / executor / log_manager",
    "CALL|initialize(config, factory, dependency_results) → EnvironmentResult",
    "CALL|finish_run() → None",
    "NOTE|负责单环境预检、上下文与结果汇总"
) $frameworkBorder

Draw-ContractBox $graphics 865 135 390 220 "EnvironmentRegistry" "类型合法性的唯一来源" @(
    "DATA|model_types: type_id → model_factory",
    "CALL|resolve(type_id) → EnvironmentModel",
    "CALL|definitions() → EnvironmentDefinition[]",
    "NOTE|仅注册类型，不保存设备运行状态"
) $frameworkBorder

Draw-ContractBox $graphics 1320 95 830 430 "«abstract» EnvironmentModel" "绿色方法：子类实现；框架在明确阶段调用" @(
    "DATA|不持有跨任务连接或运行结果",
    "IMPL|definition() → EnvironmentDefinition",
    "IMPL|validate_config(config) → ValidationReport",
    "IMPL|dependencies(config) → Dependency[]",
    "IMPL|create_log_collectors(log_context) → LogCollector[]",
    "IMPL|build_initialize_plan(control_context) → Plan",
    "IMPL|verify_ready(control_context) → ReadinessResult",
    "IMPL|collect_failure_context(context, failure) → None [可选]",
    "NOTE|参数由框架传入；返回值交回框架"
) $abstractBorder

Draw-Arrow $graphics 325 240 380 240 "调用公共API"
Draw-Arrow $graphics 810 240 865 240 "解析type_id"
Draw-Arrow $graphics 1255 240 1320 240 "创建任务级Model"

Draw-ContractBox $graphics 865 405 390 180 "EnvironmentDefinition" "EnvironmentModel提供的静态类型数据" @(
    "DATA|type_id / display_name / capabilities",
    "DATA|config_schema",
    "DATA|connection_requirements",
    "NOTE|供Registry、UI和配置校验读取"
) $boxBorder

Draw-ContractBox $graphics 1320 565 830 155 "具体EnvironmentModel" "继承抽象基类并实现全部IMPL方法" @(
    "DATA|CommonHostModel / EvbModel / DvModel",
    "DATA|CompositeEnvironmentModel",
    "IMPL|只提供环境差异，不重写公共执行主流程"
) ([System.Drawing.Color]::FromArgb(22, 163, 74))

Draw-VerticalArrow $graphics 1735 565 525 "继承 / 实现"

# Execution lane
Draw-Text $graphics "环境初始化执行链（从左到右，无跳线）" $laneFont $ink 45 755 700 32

Draw-ContractBox $graphics 45 805 370 210 "PlanExecutor" "ControlService内部调用" @(
    "DATA|本次执行状态 / 公共策略",
    "CALL|execute(model, plan, context) → EnvironmentResult",
    "NOTE|处理超时、取消、失败和unknown",
    "NOTE|不理解上电、烧录等业务含义"
) $frameworkBorder

Draw-ContractBox $graphics 465 805 285 180 "Plan" "由Model.build_initialize_plan返回" @(
    "DATA|plan_id / version / timeout",
    "DATA|phases: Phase[]",
    "NOTE|单环境、单次初始化的只读计划"
) $boxBorder

Draw-ContractBox $graphics 800 805 270 180 "Phase" "Plan包含的一级阶段" @(
    "DATA|phase_id / title",
    "DATA|steps: Step[]",
    "NOTE|只做分组，不执行设备操作"
) $boxBorder

Draw-ContractBox $graphics 1120 775 350 240 "«abstract» Step" "PlanExecutor调用execute" @(
    "DATA|step_id / timeout / side_effect",
    "DATA|retry_policy / failure_policy",
    "CALL|execute(context) → StepResult",
    "DATA|Check / EnsureState / Operation",
    "NOTE|最小可执行和可判定结果单元"
) $abstractBorder

Draw-ContractBox $graphics 1520 775 330 240 "ControlContext" "ControlService提供给Step" @(
    "DATA|config: EffectiveEnvironmentConfig",
    "DATA|cancel_event / run_directory",
    "DATA|managed_connections / step_results",
    "CALL|resolve_connection(id) → Connector",
    "NOTE|初始化结束后整体关闭"
) $boxBorder

Draw-ContractBox $graphics 1900 805 260 180 "BasicConnector" "由Context持有" @(
    "DATA|连接配置 / session状态",
    "CALL|协议操作 → 结构化结果",
    "NOTE|SSH / Serial / BMC"
) $boxBorder

Draw-Arrow $graphics 415 910 465 910 "读取Plan"
Draw-Arrow $graphics 750 910 800 910 "包含"
Draw-Arrow $graphics 1070 910 1120 910 "包含"
Draw-Arrow $graphics 1470 910 1520 910 "传入context"
Draw-Arrow $graphics 1850 910 1900 910 "解析连接"

# Logging lane
Draw-Text $graphics "独立日志链（与ControlContext连接分离）" $laneFont $ink 45 1070 700 32

Draw-ContractBox $graphics 45 1120 390 220 "LogManager" "ControlService创建；用户结束运行时关闭" @(
    "DATA|sessions: environment_id → LogSession",
    "CALL|start_environment_log_session(env_id, collectors) → LogSession",
    "CALL|stop_environment_log_session(env_id) → None",
    "NOTE|调用Model.create_log_collectors(...)"
) $frameworkBorder

Draw-ContractBox $graphics 505 1120 380 220 "LogSession" "单环境、整次运行生命周期" @(
    "DATA|environment_id / collectors[]",
    "DATA|start_errors / stop_errors",
    "CALL|start() / stop()",
    "NOTE|初始化失败后仍持续到用户结束"
) $boxBorder

Draw-ContractBox $graphics 955 1120 390 220 "LogCollector" "EnvironmentModel声明；LogSession持有" @(
    "DATA|具体Collector自行持有配置与资源",
    "DATA|连接独立于ControlContext",
    "CALL|start() / stop()",
    "NOTE|Serial / SSH / file等单一日志源"
) $boxBorder

Draw-ContractBox $graphics 1415 1120 390 220 "独立BasicConnector实例" "只服务日志采集" @(
    "DATA|独立连接与重连状态",
    "CALL|read / poll → raw log data",
    "NOTE|不得接管ControlContext连接"
) $boxBorder

Draw-ContractBox $graphics 1875 1120 285 220 "运行目录" "Collector输出归属" @(
    "DATA|env/<id>/collectors/",
    "DATA|原始日志与健康状态",
    "NOTE|用户结束运行后完成写入"
) $boxBorder

Draw-Arrow $graphics 435 1230 505 1230 "创建/管理"
Draw-Arrow $graphics 885 1230 955 1230 "持有"
Draw-Arrow $graphics 1345 1230 1415 1230 "使用独立连接"
Draw-Arrow $graphics 1805 1230 1875 1230 "写入"

# Bottom legend
Draw-RoundedRect $graphics 45 1400 2115 85 $neutralFill $boxBorder 1
$b1 = Brush $dataFill; $graphics.FillRectangle($b1, 75, 1427, 80, 26); $b1.Dispose()
Draw-Text $graphics "DATA 类提供/持有的数据" $rowFont $dataInk 165 1427 310 26
$b2 = Brush $callFill; $graphics.FillRectangle($b2, 520, 1427, 80, 26); $b2.Dispose()
Draw-Text $graphics "CALL 外部或框架调用" $rowFont $callInk 610 1427 310 26
$b3 = Brush $implFill; $graphics.FillRectangle($b3, 965, 1427, 80, 26); $b3.Dispose()
Draw-Text $graphics "IMPL 子类必须实现、框架负责调用" $rowFont $implInk 1055 1427 410 26
Draw-Text $graphics "阅读主线：外部调用 → 公共编排 → Model契约 → Plan执行；日志使用独立平行链路。" $rowBoldFont $ink 1510 1427 610 26 "Center"

$absoluteOutput = [System.IO.Path]::GetFullPath((Join-Path (Get-Location) $OutputPath))
[System.IO.Directory]::CreateDirectory([System.IO.Path]::GetDirectoryName($absoluteOutput)) | Out-Null
$bitmap.Save($absoluteOutput, [System.Drawing.Imaging.ImageFormat]::Png)

$graphics.Dispose(); $bitmap.Dispose()
$titleFont.Dispose(); $laneFont.Dispose(); $boxTitleFont.Dispose(); $rowFont.Dispose(); $rowBoldFont.Dispose(); $smallFont.Dispose()
Write-Output $absoluteOutput
