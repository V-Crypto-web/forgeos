To enhance the `TelemetryLogger` with a new `council_rejections` metric, follow these steps:

### Step 1: Modify TelemetryLogger

1. **Identify & Locate the `TelemetryLogger` class**:
   - Open the file `forgeos/observability/telemetry.py`.
   - Locate the `TelemetryLogger` class definition.

2. **Modify the `log_event` Method**:
   - Inside the `TelemetryLogger`, find the `log_event` method.
   - Add logic to check if `event_type == 'council_review'` and `approved == False`.
   - If these conditions are met, add a `council_rejections` numeric field to the JSON payload.
   - Ensure this field is initialized and incremented properly to track the total number of rejections.

3. **Ensure Backward Compatibility**:
   - Verify that existing fields such as `issue_number` and `state` remain unaffected.
   - Add test cases to ensure future changes do not inadvertently affect these critical fields.

### Step 2: Integrate with Multi-Agent Council Logic

1. **Identify Relevant Parts in Council Logic**:
   - Open the file `forgeos/agents/council.py`.
   - Review the `CouncilAgent` class and its `deliberate` method to find where a plan is rejected.

2. **Emit Telemetry Event on Rejection**:
   - In the `deliberate` method or wherever appropriate within the `CouncilAgent`, emit a telemetry event using `TelemetryLogger` whenever a plan is rejected (`approved == False`).

### Step 3: Implement & Update Tests

1. **Create/Update Unit Tests**:
   - Open the relevant test files, particularly those in `forge_bench/data/flask/tests/test_logging.py` or create new ones if necessary.
   - Add tests to ensure that `TelemetryLogger` correctly logs events with `council_rejections` when `approved == False`.

2. **Test Conditions**:
   - Ensure tests cover scenarios where `event_type == 'council_review'` and `approved == False`.
   - Test the persistence and accuracy of the `council_rejections` field over multiple invocations.

3. **Run All Tests**:
   - Execute the test suite, ensuring all tests, including those for new functionality, pass successfully.

### Step 4: Review & Document Changes

1. **Code Review**:
   - Conduct a peer review to ensure the change adheres to coding standards and meets functional requirements.
   
2. **Update Documentation**:
   - Document the changes, especially the new `council_rejections` field and its intended usage in the codebase documentation or relevant markdown files.

### Step 5: Deployment

1. **Deployment Preparation**:
   - Ensure all tests pass and conduct any necessary pre-deployment checks.
   - Prepare a deployment plan if this change needs to be rolled out in stages.

2. **Deployment**:
   - Deploy the changes to the appropriate environment (e.g., staging, production) following operational guidelines.

3. **Post-Deployment Verification**:
   - Monitor telemetry to verify that the new `council_rejections` metric works as expected in the live environment.

This plan ensures the changes are implemented, tested, and deployed smoothly while maintaining backward compatibility.