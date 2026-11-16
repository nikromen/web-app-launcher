import QtQuick
import "UiMetrics.mjs" as UiMetrics
import QtQuick.Controls
import QtQuick.Layouts

Dialog {
    id: aboutDialog
    title: "About"
    modal: true
    width: Math.min(Screen.desktopAvailableWidth * UiMetrics.aboutWidthFraction, UiMetrics.aboutMaxWidth)
    padding: UiMetrics.dialogPadding

    contentItem: ColumnLayout {
        spacing: UiMetrics.spaceLarge
        width: aboutDialog.availableWidth

        Label {
            text: Qt.application.name
            font.pixelSize: UiMetrics.fontHeading
            font.weight: Font.Bold
            Layout.fillWidth: true
            horizontalAlignment: Text.AlignHCenter
        }

        Label {
            text: "Version " + Qt.application.version
            font.pixelSize: UiMetrics.fontSecondary
            opacity: UiMetrics.opacitySecondary
            Layout.fillWidth: true
            horizontalAlignment: Text.AlignHCenter
        }

        Label {
            text: "Launch web applications as standalone apps with dedicated browser profiles " +
                  "and optional per-app system tray integration."
            wrapMode: Text.WordWrap
            Layout.fillWidth: true
            horizontalAlignment: Text.AlignHCenter
        }

        Label {
            text: "Licensed under GPL-3.0-or-later"
            font.pixelSize: UiMetrics.fontCaption
            opacity: UiMetrics.opacityHint
            Layout.fillWidth: true
            horizontalAlignment: Text.AlignHCenter
        }
    }

    footer: DialogButtonBox {
        Button {
            text: "Close"
            DialogButtonBox.buttonRole: DialogButtonBox.RejectRole
        }
    }
}
