import QtQuick
import QtQuick.Controls
import QtQuick.Layouts

Dialog {
    id: appDialog
    property bool blockCloseShortcut: false
    title: dialogController.isAppEditMode ? "Edit Application" : "New Application"
    modal: true

    width: Math.min(Screen.desktopAvailableWidth * 0.55, 720)
    padding: 24

    contentItem: ScrollView {
        clip: true
        ScrollBar.horizontal.policy: ScrollBar.AlwaysOff
        implicitHeight: Math.min(Screen.desktopAvailableHeight * 0.65, contentLayout.implicitHeight)

        ColumnLayout {
            id: contentLayout
            width: appDialog.availableWidth
            spacing: 20

            GroupBox {
                Layout.fillWidth: true
                title: "Basic Information"

                GridLayout {
                    columns: 2
                    columnSpacing: 16
                    rowSpacing: 12
                    width: parent.width

                    Label {
                        text: "Name *"
                        Layout.alignment: Qt.AlignTop
                        Layout.minimumWidth: 120
                    }
                    TextField {
                        id: nameField
                        Layout.fillWidth: true
                        placeholderText: "e.g., Gmail, GitHub, Slack..."
                        text: dialogController.appName
                        onTextChanged: dialogController.appName = text
                    }

                    Label {
                        text: "URL *"
                        Layout.alignment: Qt.AlignTop
                    }
                    RowLayout {
                        Layout.fillWidth: true
                        TextField {
                            id: urlField
                            Layout.fillWidth: true
                            placeholderText: "https://example.com"
                            text: dialogController.appUrl
                            onTextChanged: dialogController.appUrl = text
                        }
                        Button {
                            text: "Fetch Info"
                            icon.name: "download"
                            onClicked: dialogController.fetch_metadata()
                            enabled: urlField.text.length > 0
                        }
                    }

                    Label {
                        text: "Description"
                        Layout.alignment: Qt.AlignTop
                    }
                    TextArea {
                        id: descriptionField
                        Layout.fillWidth: true
                        Layout.preferredHeight: 80
                        placeholderText: "Brief description of the application..."
                        text: dialogController.appDescription
                        onTextChanged: dialogController.appDescription = text
                        wrapMode: TextArea.Wrap
                    }

                    Label {
                        text: "Icon"
                        Layout.alignment: Qt.AlignVCenter
                    }
                    RowLayout {
                        spacing: 16

                        Rectangle {
                            width: 72
                            height: 72
                            radius: 6
                            color: palette.alternateBase
                            border.color: palette.mid
                            border.width: 1

                            Image {
                                id: iconPreview
                                anchors.centerIn: parent
                                width: 56
                                height: 56
                                source: dialogController.iconPath
                                fillMode: Image.PreserveAspectFit
                                cache: false
                                smooth: true
                                visible: status === Image.Ready
                            }

                            Label {
                                anchors.centerIn: parent
                                text: dialogController.appName ? dialogController.appName.substring(0, 1).toUpperCase() : "A"
                                font.pixelSize: 28
                                font.weight: Font.DemiBold
                                opacity: 0.5
                                visible: !iconPreview.visible
                            }
                        }

                        Button {
                            text: "Choose Icon..."
                            icon.name: "document-open"
                            onClicked: dialogController.choose_icon_file()
                        }
                    }
                }
            }

            GroupBox {
                Layout.fillWidth: true
                title: "Browser Configuration"

                GridLayout {
                    columns: 2
                    columnSpacing: 16
                    rowSpacing: 12
                    width: parent.width

                    Label {
                        text: "Browser"
                        Layout.minimumWidth: 120
                    }
                    ComboBox {
                        id: browserCombo
                        Layout.fillWidth: true
                        model: dialogController.browserListModel
                        textRole: "name"
                        currentIndex: dialogController.browserListModel.get_index_by_value(dialogController.selectedBrowserKey)
                        onCurrentIndexChanged: {
                            let key = dialogController.browserListModel.get_value_by_index(currentIndex)
                            dialogController.selectedBrowserKey = key
                        }
                    }

                    Label { text: "Profile" }
                    ComboBox {
                        id: profileCombo
                        Layout.fillWidth: true
                        model: dialogController.filteredProfileModel
                        textRole: "name"
                        currentIndex: dialogController.filteredProfileModel.get_index_by_value(dialogController.selectedProfileUuid)
                        onCurrentIndexChanged: {
                            if (currentIndex > -1) {
                                let uuid = dialogController.filteredProfileModel.get_value_by_index(currentIndex)
                                dialogController.selectedProfileUuid = uuid
                            }
                        }
                    }
                }
            }

            GroupBox {
                Layout.fillWidth: true
                title: "Options"

                ColumnLayout {
                    width: parent.width
                    CheckBox {
                        id: incognitoCheck
                        text: "Private/Incognito Mode"
                        checked: dialogController.incognitoMode
                        onCheckedChanged: dialogController.incognitoMode = checked
                    }
                    CheckBox {
                        id: navBarCheck
                        text: "Show Navigation Bar"
                        checked: dialogController.showNavigationBar
                        onCheckedChanged: dialogController.showNavigationBar = checked
                    }
                }
            }

            GroupBox {
                Layout.fillWidth: true
                title: "Advanced"

                GridLayout {
                    columns: 2
                    columnSpacing: 16
                    rowSpacing: 12
                    width: parent.width

                    Label {
                        text: "Extra Arguments"
                        Layout.minimumWidth: 120
                    }
                    TextField {
                        id: extraArgsField
                        Layout.fillWidth: true
                        placeholderText: "Additional command line arguments..."
                        text: dialogController.extraArgs
                        onTextChanged: dialogController.extraArgs = text
                    }
                }
            }

            GroupBox {
                Layout.fillWidth: true
                title: "System Tray"

                ColumnLayout {
                    width: parent.width
                    spacing: 12

                    CheckBox {
                        id: trayEnabledCheck
                        text: "Enable system tray while this app is running"
                        checked: dialogController.trayEnabled
                        onCheckedChanged: dialogController.trayEnabled = checked
                    }

                    Label {
                        text: "When enabled, a tray icon appears with Show, Stop, and custom actions. " +
                              "Show script is optional and useful on Wayland."
                        wrapMode: Text.WordWrap
                        Layout.fillWidth: true
                        opacity: 0.8
                        font.pixelSize: 11
                        visible: trayEnabledCheck.checked
                    }

                    GridLayout {
                        enabled: trayEnabledCheck.checked
                        visible: trayEnabledCheck.checked
                        columns: 2
                        columnSpacing: 16
                        rowSpacing: 8
                        Layout.fillWidth: true

                        Label {
                            text: "Show script"
                            Layout.alignment: Qt.AlignVCenter
                            Layout.minimumWidth: 120
                        }
                        RowLayout {
                            Layout.fillWidth: true
                            TextField {
                                Layout.fillWidth: true
                                readOnly: true
                                placeholderText: "Optional script (WEBAPP_ACTION=show)"
                                text: dialogController.showScriptPath
                            }
                            Button {
                                text: "Browse..."
                                onClicked: dialogController.choose_show_script()
                            }
                            Button {
                                text: "Clear"
                                flat: true
                                enabled: dialogController.showScriptPath.length > 0
                                onClicked: dialogController.clear_show_script()
                            }
                        }
                    }

                    RowLayout {
                        Layout.fillWidth: true
                        visible: trayEnabledCheck.checked
                        enabled: trayEnabledCheck.checked
                        Label {
                            text: "Custom actions"
                            Layout.fillWidth: true
                            font.weight: Font.DemiBold
                        }
                        Button {
                            text: "Add Script"
                            icon.name: "list-add"
                            onClicked: dialogController.add_tray_script()
                        }
                    }

                    Frame {
                        Layout.fillWidth: true
                        Layout.preferredHeight: Math.min(160, trayScriptsList.contentHeight + 16)
                        visible: trayEnabledCheck.checked && trayScriptsList.count > 0
                        enabled: trayEnabledCheck.checked

                        ListView {
                            id: trayScriptsList
                            anchors.fill: parent
                            anchors.margins: 8
                            spacing: 6
                            clip: true
                            model: dialogController.trayScriptListModel

                            delegate: RowLayout {
                                required property string name
                                required property string description
                                required property int index

                                width: trayScriptsList.width
                                spacing: 8

                                Label {
                                    text: name
                                    font.weight: Font.Medium
                                    Layout.preferredWidth: 140
                                    elide: Text.ElideRight
                                }
                                Label {
                                    text: description
                                    Layout.fillWidth: true
                                    opacity: 0.75
                                    font.pixelSize: 11
                                    elide: Text.ElideMiddle
                                }
                                Button {
                                    text: "Remove"
                                    flat: true
                                    onClicked: dialogController.remove_tray_script_at_index(index)
                                }
                            }
                        }
                    }
                }
            }
        }
    }

    footer: DialogButtonBox {
        Button {
            id: cancelButton
            text: "Cancel"
            flat: true
            DialogButtonBox.buttonRole: DialogButtonBox.RejectRole
        }

        Button {
            id: saveButton
            text: dialogController.isAppEditMode ? "Save" : "Create"
            highlighted: true
            enabled: nameField.text.length > 0 && urlField.text.length > 0
            onClicked: dialogController.save_app()
        }
    }

    Shortcut {
        sequence: StandardKey.Save
        enabled: appDialog.visible && saveButton.enabled
        onActivated: dialogController.save_app()
    }
    Shortcut {
        sequences: [StandardKey.Cancel]
        enabled: appDialog.visible && !appDialog.blockCloseShortcut
        onActivated: appDialog.close()
    }
}
