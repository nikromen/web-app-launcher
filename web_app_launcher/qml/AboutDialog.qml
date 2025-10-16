import QtQuick
import QtQuick.Controls
import QtQuick.Layouts

Dialog {
    id: aboutDialog
    title: "About"
    modal: true
    width: Math.min(Screen.desktopAvailableWidth * 0.4, 480)
    padding: 24

    contentItem: ColumnLayout {
        spacing: 16
        width: aboutDialog.availableWidth

        Label {
            text: Qt.application.name
            font.pixelSize: 20
            font.weight: Font.Bold
            Layout.fillWidth: true
            horizontalAlignment: Text.AlignHCenter
        }

        Label {
            text: "Version " + Qt.application.version
            font.pixelSize: 12
            opacity: 0.75
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
            font.pixelSize: 11
            opacity: 0.7
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
