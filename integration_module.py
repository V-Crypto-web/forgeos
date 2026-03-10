from opportunity_detector import OpportunityDetector

def integrate_opportunity_detector(aggregated_signals):
    detector = OpportunityDetector()
    opportunities = detector.detect_opportunities(aggregated_signals)
    # Further integration logic can be added here
    return opportunities

if __name__ == "__main__":
    # Example usage
    aggregated_signals = []  # Replace with actual aggregated signals
    opportunities = integrate_opportunity_detector(aggregated_signals)
