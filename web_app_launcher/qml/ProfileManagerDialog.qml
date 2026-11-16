import QtQuick
import "UiMetrics.mjs" as UiMetrics
import QtQuick.Controls
import QtQuick.Layouts

Dialog {
    id: profileManagerDialog
    property bool blockCloseShortcut: false
    title: "Browser Profile Manager"
    modal: true

    width: Math.min(Screen.desktopAvailableWidth * UiMetrics.profileManagerWidthFraction, UiMetrics.profileManagerMaxWidth)
    height: Math.min(Screen.desktopAvailableHeight * UiMetrics.profileManagerHeightFraction, UiMetrics.profileManagerMaxHeight)
    padding: UiMetrics.dialogPadding

    contentItem: ColumnLayout {
        spacing: UiMetrics.spaceLarge
        width: profileManagerDialog.availableWidth
        height: profileManagerDialog.availableHeight

        Label {
            text: "Browser profiles store extensions, settings, and logins for web applications.\n\n" +
                  "Shared profiles are reused directly by apps. Dedicated profiles belong to a single app. " +
                  "Session templates are copied at launch and reset when the app closes."
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
                spacing: UiMetrics.spaceMedium
                width: parent.width
                implicitHeight: contentHeight
                boundsBehavior: Flickable.StopAtBounds

                model: dialogController.profileListModel

                delegate: Rectangle {
                    required property string uuid
                    required property string name
                    required property string description

                    width: profilesListView.width
                    height: profileCard.implicitHeight + UiMetrics.profileCardVerticalPadding
                    radius: UiMetrics.cardCornerRadius
                    color: palette.base
                    border.color: palette.mid
                    border.width: UiMetrics.borderWidth

                    RowLayout {
                        id: profileCard
                        anchors.fill: parent
                        anchors.margins: UiMetrics.spaceRegular
                        spacing: UiMetrics.spaceLarge

                        ColumnLayout {
                            Layout.fillWidth: true
                            spacing: UiMetrics.spaceTiny

                            Label {
                                text: name
                                font.pixelSize: UiMetrics.fontCardTitle
                                font.weight: Font.DemiBold
                                Layout.fillWidth: true
                            }
                            Label {
                                text: description
                                font.pixelSize: UiMetrics.fontSecondary
                                opacity: UiMetrics.opacitySecondary
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
            font.pixelSize: UiMetrics.fontBody
            opacity: UiMetrics.opacityEmptyState
            horizontalAlignment: Text.AlignHCenter
        }

        RowLayout {
            Layout.fillWidth: true
            spacing: UiMetrics.spaceRegular
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
