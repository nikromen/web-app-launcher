import QtQuick
import QtQuick.Controls
import QtQuick.Layouts

Dialog {
    id: iconPickerDialog
    title: "Choose Icon"
    modal: true
    width: Math.min(Screen.desktopAvailableWidth * 0.5, 560)
    padding: 24

    property var iconPaths: []

    contentItem: ColumnLayout {
        spacing: 16
        width: iconPickerDialog.availableWidth

        Label {
            text: "Multiple icons were found. Select the one you want to use:"
            wrapMode: Text.WordWrap
            Layout.fillWidth: true
        }

        Frame {
            Layout.fillWidth: true
            Layout.preferredHeight: 220

            GridView {
                id: iconsGrid
                anchors.fill: parent
                anchors.margins: 8
                cellWidth: 96
                cellHeight: 96
                clip: true
                model: iconPickerDialog.iconPaths

                ScrollBar.vertical: ScrollBar { policy: ScrollBar.AsNeeded }

                delegate: ItemDelegate {
                    width: iconsGrid.cellWidth - 8
                    height: iconsGrid.cellHeight - 8
                    highlighted: iconsGrid.currentIndex === index

                    contentItem: Image {
                        anchors.fill: parent
                        anchors.margins: 8
                        source: modelData
                        fillMode: Image.PreserveAspectFit
                        cache: false
                    }

                    onClicked: {
                        iconsGrid.currentIndex = index
                        dialogController.select_fetched_icon(modelData)
                        iconPickerDialog.close()
                    }
                }
            }
        }
    }

    footer: DialogButtonBox {
        Button {
            text: "Cancel"
            flat: true
            DialogButtonBox.buttonRole: DialogButtonBox.RejectRole
        }
    }

    Shortcut {
        sequences: [StandardKey.Cancel]
        enabled: iconPickerDialog.visible
        onActivated: iconPickerDialog.close()
    }
}
