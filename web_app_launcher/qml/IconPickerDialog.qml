import QtQuick
import "UiMetrics.mjs" as UiMetrics
import QtQuick.Controls
import QtQuick.Layouts

Dialog {
    id: iconPickerDialog
    title: "Choose Icon"
    modal: true
    width: Math.min(Screen.desktopAvailableWidth * UiMetrics.iconPickerWidthFraction, UiMetrics.iconPickerMaxWidth)
    padding: UiMetrics.dialogPadding

    property var iconPaths: []

    contentItem: ColumnLayout {
        spacing: UiMetrics.spaceLarge
        width: iconPickerDialog.availableWidth

        Label {
            text: "Multiple icons were found. Select the one you want to use:"
            wrapMode: Text.WordWrap
            Layout.fillWidth: true
        }

        Frame {
            Layout.fillWidth: true
            Layout.preferredHeight: UiMetrics.iconPickerGridHeight

            GridView {
                id: iconsGrid
                anchors.fill: parent
                anchors.margins: UiMetrics.spaceCompact
                cellWidth: UiMetrics.iconPickerCellSize
                cellHeight: UiMetrics.iconPickerCellSize
                clip: true
                model: iconPickerDialog.iconPaths

                ScrollBar.vertical: ScrollBar { policy: ScrollBar.AsNeeded }

                delegate: ItemDelegate {
                    width: iconsGrid.cellWidth - UiMetrics.spaceCompact
                    height: iconsGrid.cellHeight - UiMetrics.spaceCompact
                    highlighted: iconsGrid.currentIndex === index

                    contentItem: Image {
                        anchors.fill: parent
                        anchors.margins: UiMetrics.spaceCompact
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
