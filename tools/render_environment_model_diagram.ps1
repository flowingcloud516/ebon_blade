param(
    [string]$OutputPath = "design/images/environment-model-class-map.png"
)

Add-Type -AssemblyName System.Drawing
$ErrorActionPreference = "Stop"

$width = 1800
$height = 1260
$bitmap = New-Object System.Drawing.Bitmap($width, $height)
$graphics = [System.Drawing.Graphics]::FromImage($bitmap)
$graphics.SmoothingMode = [System.Drawing.Drawing2D.SmoothingMode]::AntiAlias
$graphics.TextRenderingHint = [System.Drawing.Text.TextRenderingHint]::ClearTypeGridFit
$graphics.Clear([System.Drawing.Color]::FromArgb(247, 249, 252))

$fontName = "Microsoft YaHei UI"
$titleFont = New-Object System.Drawing.Font($fontName, 25, [System.Drawing.FontStyle]::Bold)
$subtitleFont = New-Object System.Drawing.Font($fontName, 12, [System.Drawing.FontStyle]::Regular)
$boxTitleFont = New-Object System.Drawing.Font($fontName, 13, [System.Drawing.FontStyle]::Bold)
$boxFont = New-Object System.Drawing.Font($fontName, 11, [System.Drawing.FontStyle]::Regular)
$keyFont = New-Object System.Drawing.Font($fontName, 11, [System.Drawing.FontStyle]::Bold)
$legendFont = New-Object System.Drawing.Font($fontName, 10, [System.Drawing.FontStyle]::Regular)

$textColor = [System.Drawing.Color]::FromArgb(31, 41, 55)
$mutedColor = [System.Drawing.Color]::FromArgb(75, 85, 99)
$lineColor = [System.Drawing.Color]::FromArgb(100, 116, 139)
$frameworkFill = [System.Drawing.Color]::FromArgb(219, 234, 254)
$frameworkBorder = [System.Drawing.Color]::FromArgb(37, 99, 235)
$abstractFill = [System.Drawing.Color]::FromArgb(254, 243, 199)
$abstractBorder = [System.Drawing.Color]::FromArgb(217, 119, 6)
$concreteFill = [System.Drawing.Color]::FromArgb(220, 252, 231)
$concreteBorder = [System.Drawing.Color]::FromArgb(22, 163, 74)
$runtimeFill = [System.Drawing.Color]::FromArgb(243, 232, 255)
$runtimeBorder = [System.Drawing.Color]::FromArgb(147, 51, 234)
$keyFill = [System.Drawing.Color]::FromArgb(255, 247, 214)
$white = [System.Drawing.Color]::White

function New-Brush([System.Drawing.Color]$color) {
    return New-Object System.Drawing.SolidBrush($color)
}

function Draw-RoundedRect($g, $rect, $radius, $fill, $border, $borderWidth = 2) {
    $path = New-Object System.Drawing.Drawing2D.GraphicsPath
    $diameter = $radius * 2
    $path.AddArc($rect.X, $rect.Y, $diameter, $diameter, 180, 90)
    $path.AddArc($rect.Right - $diameter, $rect.Y, $diameter, $diameter, 270, 90)
    $path.AddArc($rect.Right - $diameter, $rect.Bottom - $diameter, $diameter, $diameter, 0, 90)
    $path.AddArc($rect.X, $rect.Bottom - $diameter, $diameter, $diameter, 90, 90)
    $path.CloseFigure()
    $fillBrush = New-Brush $fill
    $pen = New-Object System.Drawing.Pen($border, $borderWidth)
    $g.FillPath($fillBrush, $path)
    $g.DrawPath($pen, $path)
    $fillBrush.Dispose()
    $pen.Dispose()
    $path.Dispose()
}

function Draw-Text($g, $text, $font, $color, $x, $y, $w, $h, $alignment = "Near") {
    $brush = New-Brush $color
    $format = New-Object System.Drawing.StringFormat
    $format.Alignment = [System.Drawing.StringAlignment]::$alignment
    $format.LineAlignment = [System.Drawing.StringAlignment]::Near
    $format.Trimming = [System.Drawing.StringTrimming]::EllipsisCharacter
    $g.DrawString($text, $font, $brush, (New-Object System.Drawing.RectangleF($x, $y, $w, $h)), $format)
    $format.Dispose()
    $brush.Dispose()
}

function Draw-Box($g, $x, $y, $w, $h, $title, $lines, $fill, $border, $keyLines = @()) {
    $rect = New-Object System.Drawing.Rectangle($x, $y, $w, $h)
    Draw-RoundedRect $g $rect 12 $fill $border 2
    Draw-Text $g $title $boxTitleFont $textColor ($x + 14) ($y + 10) ($w - 28) 30 "Center"
    $divider = New-Object System.Drawing.Pen($border, 1)
    $g.DrawLine($divider, $x + 12, $y + 45, $x + $w - 12, $y + 45)
    $divider.Dispose()
    $lineY = $y + 54
    foreach ($line in $lines) {
        if ($keyLines -contains $line) {
            $highlight = New-Brush $keyFill
            $g.FillRectangle($highlight, $x + 10, $lineY - 2, $w - 20, 25)
            $highlight.Dispose()
            $displayLine = if ($line.StartsWith("★")) { $line } else { "★ " + $line }
            Draw-Text $g $displayLine $keyFont $textColor ($x + 16) $lineY ($w - 32) 24
        } else {
            Draw-Text $g $line $boxFont $textColor ($x + 16) $lineY ($w - 32) 24
        }
        $lineY += 27
    }
}

function Draw-Arrow($g, $x1, $y1, $x2, $y2, $label = "", $dashed = $false) {
    $pen = New-Object System.Drawing.Pen($lineColor, 2)
    if ($dashed) { $pen.DashStyle = [System.Drawing.Drawing2D.DashStyle]::Dash }
    $g.DrawLine($pen, $x1, $y1, $x2, $y2)
    $angle = [Math]::Atan2($y2 - $y1, $x2 - $x1)
    $size = 10
    $p1 = [System.Drawing.PointF]::new([single]$x2, [single]$y2)
    $p2 = [System.Drawing.PointF]::new(
        [single]($x2 - $size * [Math]::Cos($angle - [Math]::PI / 6)),
        [single]($y2 - $size * [Math]::Sin($angle - [Math]::PI / 6))
    )
    $p3 = [System.Drawing.PointF]::new(
        [single]($x2 - $size * [Math]::Cos($angle + [Math]::PI / 6)),
        [single]($y2 - $size * [Math]::Sin($angle + [Math]::PI / 6))
    )
    $arrowBrush = New-Brush $lineColor
    $points = [System.Drawing.PointF[]]@($p1, $p2, $p3)
    $g.FillPolygon($arrowBrush, $points)
    $arrowBrush.Dispose()
    $pen.Dispose()
    if ($label) {
        $midX = [int](($x1 + $x2) / 2) - 70
        $midY = [int](($y1 + $y2) / 2) - 18
        Draw-Text $g $label $legendFont $mutedColor $midX $midY 140 22 "Center"
    }
}

Draw-Text $graphics "Environment Model 类与关键接口" $titleFont $textColor 40 24 1720 42 "Center"
Draw-Text $graphics "蓝色：框架公共实现（具体环境不得覆盖） · 橙色：核心抽象基类 · 绿色：具体环境实现 · 紫色：运行时对象" $subtitleFont $mutedColor 40 68 1720 28 "Center"

# Framework-owned classes
Draw-Box $graphics 50 130 300 155 "EnvironmentRegistry" @(
    "+ register(type_id, model_type)",
    "+ resolve(type_id)",
    "+ definitions()"
) $frameworkFill $frameworkBorder @("+ resolve(type_id)")

Draw-Box $graphics 50 355 300 155 "EnvironmentControlService" @(
    "+ initialize(environment_id)",
    "+ validate_dependencies()",
    "+ finish_run()"
) $frameworkFill $frameworkBorder @("+ initialize(environment_id)")

Draw-Box $graphics 50 580 300 155 "PlanExecutor" @(
    "+ execute(model, plan, context)",
    "+ enforce_timeout_cancel()",
    "+ aggregate_result()"
) $frameworkFill $frameworkBorder @("+ execute(model, plan, context)")

Draw-Box $graphics 50 805 300 155 "LogManager" @(
    "+ start_log_session(env_id)",
    "+ stop_log_session(env_id)",
    "+ close_run()"
) $frameworkFill $frameworkBorder @("+ start_log_session(env_id)", "+ stop_log_session(env_id)")

# Abstract model, highlighted required methods
$modelLines = @(
    "definition()",
    "validate_config(config)",
    "dependencies(config)",
    "create_log_collectors(context)",
    "build_initialize_plan(context)",
    "verify_ready(context)",
    "collect_failure_context(...) [可选]"
)
Draw-Box $graphics 475 155 470 300 "«abstract» EnvironmentModel" $modelLines $abstractFill $abstractBorder @(
    "definition()",
    "validate_config(config)",
    "dependencies(config)",
    "create_log_collectors(context)",
    "build_initialize_plan(context)",
    "verify_ready(context)"
)

Draw-Box $graphics 475 505 470 150 "EnvironmentDefinition" @(
    "+ type_id / display_name",
    "+ config_schema",
    "+ connection_requirements",
    "+ capabilities"
) $runtimeFill $runtimeBorder @("+ config_schema", "+ connection_requirements")

# Concrete models
Draw-Box $graphics 420 760 230 115 "CommonHostModel" @("实现全部★接口", "通用主机步骤") $concreteFill $concreteBorder
Draw-Box $graphics 675 760 230 115 "EvbModel" @("实现全部★接口", "EVB启动步骤") $concreteFill $concreteBorder
Draw-Box $graphics 420 910 230 115 "DvModel" @("实现全部★接口", "内部DV步骤") $concreteFill $concreteBorder
Draw-Box $graphics 675 910 230 115 "CompositeModel" @("实现全部★接口", "跨环境协调") $concreteFill $concreteBorder

# Runtime plan and logging side
Draw-Box $graphics 1110 130 270 120 "Plan" @("+ phases: Phase[]", "结构在执行前确定") $runtimeFill $runtimeBorder @("+ phases: Phase[]")
Draw-Box $graphics 1110 310 270 120 "Phase" @("+ phase_id / title", "+ steps: Step[]") $runtimeFill $runtimeBorder
Draw-Box $graphics 1050 490 390 190 "«abstract» Step" @(
    "+ step_id / timeout",
    "+ side_effect / failure_policy",
    "+ execute(context)",
    "子类：Check / EnsureState / Operation"
) $abstractFill $abstractBorder @("+ execute(context)")

Draw-Box $graphics 1040 765 300 145 "ControlContext" @(
    "+ managed connections",
    "+ cancel / results",
    "+ resolve_connection(id)"
) $runtimeFill $runtimeBorder @("+ resolve_connection(id)")

Draw-Box $graphics 1450 765 290 145 "BasicConnector" @(
    "SSH / Serial / BMC",
    "由Context统一提供",
    "禁止全局私建连接"
) $runtimeFill $runtimeBorder

Draw-Box $graphics 1040 1000 300 135 "LogSession" @(
    "+ independent connections",
    "+ collectors[]",
    "直到用户结束运行"
) $runtimeFill $runtimeBorder

Draw-Box $graphics 1450 1000 290 135 "LogCollector" @(
    "Serial / SSH / file...",
    "由Model声明",
    "由LogSession持有"
) $runtimeFill $runtimeBorder

# Relationships
Draw-Arrow $graphics 350 205 475 230 "注册/解析"
Draw-Arrow $graphics 350 430 475 355 "解析Model"
Draw-Arrow $graphics 350 430 350 655 "调用" $true
Draw-Arrow $graphics 350 655 1050 585 "执行Plan"
Draw-Arrow $graphics 710 455 710 505 "定义"
Draw-Arrow $graphics 710 455 1190 190 "构造Plan"
Draw-Arrow $graphics 1245 250 1245 310 "包含"
Draw-Arrow $graphics 1245 430 1245 490 "包含"
Draw-Arrow $graphics 1245 680 1190 765 "使用Context"
Draw-Arrow $graphics 1340 838 1450 838 "提供连接"
Draw-Arrow $graphics 350 880 1040 1065 "管理" $true
Draw-Arrow $graphics 1340 1068 1450 1068 "持有"
Draw-Arrow $graphics 945 350 1450 1068 "声明Collector" $true

# Inheritance connectors
$inheritPen = New-Object System.Drawing.Pen($concreteBorder, 2)
$inheritPen.DashStyle = [System.Drawing.Drawing2D.DashStyle]::Dash
$graphics.DrawLine($inheritPen, 590, 760, 640, 455)
$graphics.DrawLine($inheritPen, 790, 760, 760, 455)
$graphics.DrawLine($inheritPen, 590, 910, 680, 455)
$graphics.DrawLine($inheritPen, 790, 910, 800, 455)
$inheritPen.Dispose()
Draw-Text $graphics "继承并实现★接口" $legendFont $concreteBorder 505 700 350 25 "Center"

# Review callout
Draw-Box $graphics 50 1040 855 150 "评审时重点关注" @(
    "★ EnvironmentModel六个必实现函数是否足够且职责清晰",
    "★ EnvironmentControlService / PlanExecutor / LogManager由框架统一实现",
    "★ Model只能声明Plan与Collector，连接必须从Context取得"
) $white $abstractBorder @(
    "★ EnvironmentModel六个必实现函数是否足够且职责清晰",
    "★ EnvironmentControlService / PlanExecutor / LogManager由框架统一实现",
    "★ Model只能声明Plan与Collector，连接必须从Context取得"
)

$absoluteOutput = [System.IO.Path]::GetFullPath((Join-Path (Get-Location) $OutputPath))
$outputDirectory = [System.IO.Path]::GetDirectoryName($absoluteOutput)
[System.IO.Directory]::CreateDirectory($outputDirectory) | Out-Null
$bitmap.Save($absoluteOutput, [System.Drawing.Imaging.ImageFormat]::Png)

$graphics.Dispose()
$bitmap.Dispose()
$titleFont.Dispose()
$subtitleFont.Dispose()
$boxTitleFont.Dispose()
$boxFont.Dispose()
$keyFont.Dispose()
$legendFont.Dispose()

Write-Output $absoluteOutput
