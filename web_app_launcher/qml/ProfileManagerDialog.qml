import QtQuick
import QtQuick.Controls
import QtQuick.Layouts

Dialog {
    id: profileManagerDialog
    property bool blockCloseShortcut: false
    title: "Browser Profile Manager"
    modal: true

    width: Math.min(Screen.desktopAvailableWidth * 0.5, 720)
    height: Math.min(Screen.desktopAvailableHeight * 0.6, 620)
    padding: 24

    contentItem: ColumnLayout {
        spacing: 16
        width: profileManagerDialog.availableWidth
        height: profileManagerDialog.availableHeight

        Label {
            text: "Browser profiles let you pre-configure extensions, settings, and preferences for web applications."
            wrapMode: Text.WordWrap
            Layout.fillWidth: true
        }

        ScrollView {
            Layout.fillWidth: true
            Layout.fillHeight: true
            clip: true
            ScrollBar.horizontal.policy: ScrollBar.AlwaysOff

            ListView {
                id: profilesListView
                spacing: 10
                width: parent.width
                implicitHeight: contentHeight
                boundsBehavior: Flickable.StopAtBounds

                model: dialogController.profileListModel

                delegate: Rectangle {
                    required property string uuid
                    required property string name
                    required property string description

                    width: profilesListView.width
                    height: profileCard.implicitHeight + 24
                    radius: 8
                    color: palette.base
                    border.color: palette.mid
                    border.width: 1

                    RowLayout {
                        id: profileCard
                        anchors.fill: parent
                        anchors.margins: 12
                        spacing: 16

                        ColumnLayout {
                            Layout.fillWidth: true
                            spacing: 4

                            Label {
                                text: name
                                font.pixelSize: 15
                                font.weight: Font.DemiBold
                                Layout.fillWidth: true
                            }
                            Label {
                                text: description
                                font.pixelSize: 12
                                opacity: 0.75
                                Layout.fillWidth: true
                                wrapMode: Text.WordWrap
                            }
                        }

                        Button {
                            text: "Configure"
                            icon.name: "system-run"
                            onClicked: dialogController.configure_profile(uuid)
                            ToolTip.visible: hovered
                            ToolTip.text: "Open this browser profile so you can install extensions, sign in, and change settings."
                        }
                        Button {
                            text: "Edit"
                            icon.name: "document-edit"
                            onClicked: dialogController.open_profile_edit_dialog(uuid)
                        }
                        Button {
                            text: "Delete"
                            icon.name: "edit-delete"
                            onClicked: dialogController.remove_profile(uuid)
                        }
                    }
                }
            }
        }

        Label {
            Layout.fillWidth: true
            visible: profilesListView.count === 0
            text: "No profiles yet.\nClick \"Create Profile\" to add one."
            font.pixelSize: 14
            opacity: 0.6
            horizontalAlignment: Text.AlignHCenter
        }

        RowLayout {
            Layout.fillWidth: true
            spacing: 12
            Button {
                text: "Create Profile"
                icon.name: "list-add"
                highlighted: true
                onClicked: dialogController.open_profile_edit_dialog("")
            }
            Item { Layout.fillWidth: true }
            Button {
                text: "Close"
                onClicked: profileManagerDialog.close()
            }
        }
    }

    Shortcut {
        sequences: [StandardKey.Cancel]
        enabled: profileManagerDialog.visible && !profileManagerDialog.blockCloseShortcut
        onActivated: profileManagerDialog.close()
    }
}
