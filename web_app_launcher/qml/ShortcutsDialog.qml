import QtQuick
import QtQuick.Controls
import QtQuick.Layouts

Dialog {
    id: shortcutsDialog
    title: "Keyboard Shortcuts"
    modal: true
    width: Math.min(Screen.desktopAvailableWidth * 0.45, 520)
    padding: 24

    contentItem: ScrollView {
        clip: true
        ScrollBar.horizontal.policy: ScrollBar.AlwaysOff
        implicitHeight: Math.min(Screen.desktopAvailableHeight * 0.65, contentLayout.implicitHeight)

        ColumnLayout {
            id: contentLayout
            width: shortcutsDialog.availableWidth
            spacing: 20

            ShortcutSection {
                title: "Main Window"
                Layout.fillWidth: true
                shortcuts: [
                    { keys: "Ctrl+F, /", action: "Focus search" },
                    { keys: "↑ ↓ ← →", action: "Navigate applications" },
                    { keys: "Home / End", action: "First / last application" },
                    { keys: "Enter", action: "Launch selected application" },
                    { keys: "Ctrl+N", action: "Add new application" },
                    { keys: "F2", action: "Edit selected application" },
                    { keys: "Delete", action: "Remove selected application" },
                    { keys: "Escape", action: "Clear search or clear selection" },
                    { keys: "Ctrl+Shift+P", action: "Manage profiles" },
                    { keys: "Ctrl+Shift+I", action: "Import configuration" },
                    { keys: "Ctrl+Shift+E", action: "Export configuration" }
                ]
            }

            ShortcutSection {
                title: "Dialogs"
                Layout.fillWidth: true
                shortcuts: [
                    { keys: "Ctrl+S", action: "Save (Add/Edit Application, Profile)" },
                    { keys: "Escape", action: "Close dialog" }
                ]
            }
        }
    }

    footer: DialogButtonBox {
        Button {
            text: "Close"
            DialogButtonBox.buttonRole: DialogButtonBox.RejectRole
        }
    }

    component ShortcutSection: ColumnLayout {
        id: sectionRoot
        property string title
        property var shortcuts: []

        spacing: 8

        Label {
            text: title
            font.pixelSize: 14
            font.weight: Font.DemiBold
        }

        Frame {
            Layout.fillWidth: true
            padding: 12

            ColumnLayout {
                width: parent.availableWidth
                spacing: 8

                Repeater {
                    model: sectionRoot.shortcuts

                    RowLayout {
                        required property var modelData
                        Layout.fillWidth: true
                        spacing: 16

                        Label {
                            text: modelData.keys
                            font.family: "monospace"
                            font.pixelSize: 12
                            Layout.preferredWidth: 140
                        }
                        Label {
                            text: modelData.action
                            Layout.fillWidth: true
                            wrapMode: Text.WordWrap
                        }
                    }
                }
            }
        }
    }
}
