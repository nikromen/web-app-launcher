import QtQuick
import QtQuick.Controls
import QtQuick.Layouts

Dialog {
    id: profileDialog
    property bool blockCloseShortcut: false
    title: dialogController.isProfileEditMode ? "Edit Profile" : "New Profile"
    modal: true

    width: Math.min(Screen.desktopAvailableWidth * 0.4, 520)
    padding: 24

    contentItem: GridLayout {
        columns: 2
        columnSpacing: 16
        rowSpacing: 12
        width: profileDialog.availableWidth

        Label {
            text: "Profile Name *"
            Layout.alignment: Qt.AlignTop
            Layout.minimumWidth: 120
        }
        TextField {
            id: profileNameField
            Layout.fillWidth: true
            placeholderText: "e.g., Work Profile, Personal, Development..."
            text: dialogController.profileName
            onTextChanged: dialogController.profileName = text
        }

        Label {
            text: "Browser *"
            Layout.alignment: Qt.AlignTop
        }
        ColumnLayout {
            Layout.fillWidth: true
            ComboBox {
                id: browserCombo
                Layout.fillWidth: true
                model: dialogController.browserListModel
                textRole: "name"
                currentIndex: dialogController.browserListModel.get_index_by_value(dialogController.profileBrowserKey)
                onCurrentIndexChanged: {
                    let key = dialogController.browserListModel.get_value_by_index(currentIndex)
                    dialogController.profileBrowserKey = key
                }
                enabled: !dialogController.isProfileEditMode
            }
            Label {
                text: "Browser cannot be changed after creation"
                font.pixelSize: 10
                opacity: 0.7
                font.italic: true
                visible: dialogController.isProfileEditMode
            }
        }

        Label {
            text: "Description"
            Layout.alignment: Qt.AlignTop
        }
        TextArea {
            id: descriptionField
            Layout.fillWidth: true
            Layout.preferredHeight: 100
            placeholderText: "Describe the purpose of this profile..."
            text: dialogController.profileDescription
            onTextChanged: dialogController.profileDescription = text
            wrapMode: TextArea.Wrap
        }
    }

    footer: DialogButtonBox {
        Button {
            text: "Cancel"
            flat: true
            DialogButtonBox.buttonRole: DialogButtonBox.RejectRole
        }

        Button {
            id: saveProfileButton
            text: dialogController.isProfileEditMode ? "Save" : "Create"
            highlighted: true
            enabled: profileNameField.text.length > 0
            onClicked: dialogController.save_profile()
        }
    }

    Shortcut {
        sequence: StandardKey.Save
        enabled: profileDialog.visible && saveProfileButton.enabled
        onActivated: dialogController.save_profile()
    }
    Shortcut {
        sequences: [StandardKey.Cancel]
        enabled: profileDialog.visible && !profileDialog.blockCloseShortcut
        onActivated: profileDialog.close()
    }
}
