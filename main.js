let totalCost = 0;
const costThresholds = {
    low: 50,
    medium: 100,
    high: 200
};

function updateTotalCost(newCost) {
    totalCost += newCost;
    const badge = document.getElementById('totalCostBadge');
    badge.textContent = `Total Cost: $${totalCost.toFixed(2)}`;
    updateBadgeColor(badge);
}

function updateBadgeColor(badge) {
    if (totalCost < costThresholds.low) {
        badge.style.color = 'green';
    } else if (totalCost < costThresholds.medium) {
        badge.style.color = 'orange';
    } else {
