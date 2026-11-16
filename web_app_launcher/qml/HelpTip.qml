import QtQuick
import "UiMetrics.mjs" as UiMetrics
import QtQuick.Controls

ToolButton {
    id: control

    required property string tipText

    implicitWidth: UiMetrics.helpTipSize
    implicitHeight: UiMetrics.helpTipSize
    padding: 0
    hoverEnabled: true

    contentItem: Label {
        text: "?"
        horizontalAlignment: Text.AlignHCenter
        verticalAlignment: Text.AlignVCenter
        font.pixelSize: UiMetrics.fontSecondary
        font.weight: Font.Bold
        color: control.hovered ? palette.highlightedText : palette.buttonText
    }

    background: Rectangle {
        radius: width / 2
        color: control.hovered ? palette.highlight : palette.button
        border.color: control.hovered ? palette.highlight : palette.mid
        border.width: UiMetrics.borderWidth
    }

    ToolTip.visible: control.hovered
    ToolTip.text: tipText
    ToolTip.delay: UiMetrics.tooltipDelayMs
}
