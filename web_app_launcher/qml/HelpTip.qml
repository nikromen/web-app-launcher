import QtQuick
import QtQuick.Controls

ToolButton {
    id: control

    required property string tipText

    implicitWidth: 20
    implicitHeight: 20
    padding: 0
    hoverEnabled: true

    contentItem: Label {
        text: "?"
        horizontalAlignment: Text.AlignHCenter
        verticalAlignment: Text.AlignVCenter
        font.pixelSize: 12
        font.weight: Font.Bold
        color: control.hovered ? palette.highlightedText : palette.buttonText
    }

    background: Rectangle {
        radius: width / 2
        color: control.hovered ? palette.highlight : palette.button
        border.color: control.hovered ? palette.highlight : palette.mid
        border.width: 1
    }

    ToolTip.visible: control.hovered
    ToolTip.text: tipText
    ToolTip.delay: 300
}
