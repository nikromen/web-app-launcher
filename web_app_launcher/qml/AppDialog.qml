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
                            ToolTip.visible: hovered
                            ToolTip.text: "Download the page title, description, and icon from the URL."
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

                    RowLayout {
                        spacing: 4
                        Layout.minimumWidth: 120
                        Label { text: "Profile mode" }
                        HelpTip {
                            tipText: "Shared — use an existing profile directly; cookies and extensions are shared with other apps on the same profile.\n\n" +
                                     "Dedicated — this app gets its own profile folder. Copy a template or start empty; changes stay with this app only.\n\n" +
                                     "Session template — each launch starts from a copy of the selected profile. Session data is discarded when the app closes."
                        }
                    }
                    ComboBox {
                        id: profileModeCombo
                        Layout.fillWidth: true
                        model: dialogController.profileModeListModel
                        textRole: "name"
                        currentIndex: dialogController.profileModeListModel.get_index_by_value(dialogController.profileMode)
                        onCurrentIndexChanged: {
                            let mode = dialogController.profileModeListModel.get_value_by_index(currentIndex)
                            dialogController.profileMode = mode
                        }
                    }

                    Item {
                        Layout.columnSpan: 2
                        Layout.fillWidth: true
                        implicitHeight: profileModeDescriptionLabel.implicitHeight

                        Label {
                            id: profileModeDescriptionLabel
                            width: parent.width
                            wrapMode: Text.WordWrap
                            opacity: 0.8
                            font.pixelSize: 12
                            text: dialogController.profileModeDescription
                        }
                    }

                    RowLayout {
                        spacing: 4
                        Layout.minimumWidth: 120
                        visible: dialogController.profileSourceEnabled
                        Label {
                            text: dialogController.profileMode === "dedicated" ? "Template profile" : "Source profile"
                        }
                        HelpTip {
                            tipText: {
                                if (dialogController.profileMode === "shared") {
                                    return "Select the profile this app will use directly."
                                }
                                if (dialogController.profileMode === "dedicated") {
                                    return "Optional template to copy when creating this app's profile. Choose \"Empty profile\" to start from scratch."
                                }
                                return "Profile copied at launch. Configure extensions and logins in Profile Manager; they apply on the next start."
                            }
                        }
                    }
                    ComboBox {
                        id: profileCombo
                        Layout.fillWidth: true
                        visible: dialogController.profileSourceEnabled
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

                    Label {
                        Layout.columnSpan: 2
                        Layout.fillWidth: true
                        visible: !dialogController.profileSourceEnabled && dialogController.dedicatedProfileSummary.length > 0
                        wrapMode: Text.WordWrap
                        opacity: 0.8
                        font.pixelSize: 12
                        text: dialogController.dedicatedProfileSummary
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

                    RowLayout {
                        spacing: 4
                        Layout.minimumWidth: 120
                        Label { text: "Extra Arguments" }
                        HelpTip {
                            tipText: "Extra flags appended to the browser launch command. Separate values with spaces, for example: --new-window"
                        }
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

                    RowLayout {
                        spacing: 4
                        CheckBox {
                            id: trayEnabledCheck
                            text: "Enable system tray while this app is running"
                            checked: dialogController.trayEnabled
                            onCheckedChanged: dialogController.trayEnabled = checked
                        }
                        HelpTip {
                            tipText: "Shows a tray icon while the app is running. Right-click for Show, Stop, and any custom actions you add below."
                        }
                    }

                    GridLayout {
                        enabled: trayEnabledCheck.checked
                        visible: trayEnabledCheck.checked
                        columns: 2
                        columnSpacing: 16
                        rowSpacing: 8
                        Layout.fillWidth: true

                        RowLayout {
                            spacing: 4
                            Layout.alignment: Qt.AlignVCenter
                            Layout.minimumWidth: 120
                            Label { text: "Show command" }
                            HelpTip {
                                tipText: "Optional shell command run via bash -c when you choose Show from the tray. Built-in window focus is used only if this is empty or the command fails. Often needed on Wayland. Environment: WEBAPP_ACTION=show, WEBAPP_UUID, WEBAPP_NAME, WEBAPP_URL, WEBAPP_PID, WEBAPP_PROFILE_PATH."
                            }
                        }
                        TextField {
                            Layout.fillWidth: true
                            placeholderText: 'e.g. wmctrl -a "$WEBAPP_NAME"'
                            text: dialogController.showScriptCommand
                            onTextChanged: dialogController.showScriptCommand = text
                        }
                    }

                    RowLayout {
                        Layout.fillWidth: true
                        visible: trayEnabledCheck.checked
                        enabled: trayEnabledCheck.checked
                        RowLayout {
                            Layout.fillWidth: true
                            spacing: 4
                            Label {
                                text: "Custom actions"
                                Layout.fillWidth: true
                                font.weight: Font.DemiBold
                            }
                            HelpTip {
                                tipText: "Shell commands added to the tray menu. Each runs via bash -c with WEBAPP_ACTION=script and the same WEBAPP_* environment variables as the show command."
                            }
                        }
                        Button {
                            text: "Add Action"
                            icon.name: "list-add"
                            onClicked: dialogController.add_tray_script()
                        }
                    }

                    Frame {
                        Layout.fillWidth: true
                        Layout.preferredHeight: Math.min(240, trayScriptsList.contentHeight + 16)
                        visible: trayEnabledCheck.checked && trayScriptsList.count > 0
                        enabled: trayEnabledCheck.checked

                        ListView {
                            id: trayScriptsList
                            anchors.fill: parent
                            anchors.margins: 8
                            spacing: 10
                            clip: true
                            model: dialogController.trayScriptListModel

                            delegate: ColumnLayout {
                                required property string name
                                required property string description
                                required property int index

                                width: trayScriptsList.width
                                spacing: 6

                                RowLayout {
                                    Layout.fillWidth: true
                                    spacing: 8

                                    Label {
                                        text: "Name"
                                        Layout.preferredWidth: 56
                                    }
                                    TextField {
                                        id: actionNameField
                                        Layout.fillWidth: true
                                        text: name
                                        placeholderText: "Menu label"
                                        onTextChanged: dialogController.update_tray_script_at_index(
                                            index, text, actionCommandField.text)
                                    }
                                    Button {
                                        text: "Remove"
                                        flat: true
                                        onClicked: dialogController.remove_tray_script_at_index(index)
                                    }
                                }

                                RowLayout {
                                    Layout.fillWidth: true
                                    spacing: 8

                                    Label {
                                        text: "Command"
                                        Layout.preferredWidth: 56
                                        Layout.alignment: Qt.AlignTop
                                        topPadding: 8
                                    }
                                    TextField {
                                        id: actionCommandField
                                        Layout.fillWidth: true
                                        text: description
                                        placeholderText: 'e.g. notify-send "Hello"'
                                        onTextChanged: dialogController.update_tray_script_at_index(
                                            index, actionNameField.text, text)
                                    }
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
