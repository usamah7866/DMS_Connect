document.addEventListener("DOMContentLoaded", function () {
    const audienceField = document.getElementById("id_audience");
    const selectAllField = document.getElementById("id_select_all_classes");
    const classCheckboxes = Array.from(
        document.querySelectorAll("#id_target_classes input[type='checkbox']")
    );

    function syncClassSection() {
        const classSection = document.querySelector(".form-row.field-target_classes");
        const selectAllSection = document.querySelector(".form-row.field-select_all_classes");
        if (!classSection || !selectAllSection || !audienceField) {
            return;
        }
        const isClassWise = audienceField.value === "classwise";
        classSection.style.display = isClassWise ? "" : "none";
        selectAllSection.style.display = isClassWise ? "" : "none";
    }

    function toggleAllClasses() {
        if (!selectAllField) {
            return;
        }
        classCheckboxes.forEach((checkbox) => {
            checkbox.checked = selectAllField.checked;
        });
    }

    if (audienceField) {
        audienceField.addEventListener("change", syncClassSection);
        syncClassSection();
    }

    if (selectAllField) {
        selectAllField.addEventListener("change", toggleAllClasses);
    }
});
