(function () {
    function getGpaClass(value) {
        if (value >= 3.5) return 'gpa-excellent';
        if (value >= 3.0) return 'gpa-good';
        if (value >= 2.5) return 'gpa-average';
        return 'gpa-poor';
    }

    function isPromotedStatus(status) {
        return ['Promoted', 'Passed', 'Passed All'].includes(status);
    }

    window.DUCrackResults = {
        getGpaClass,
        isPromotedStatus,
    };
})();