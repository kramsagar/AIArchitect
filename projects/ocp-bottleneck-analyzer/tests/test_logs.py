from ocp_analyzer.logs import analyze_log, analyze_logs, template_of


def test_categories_and_samples():
    text = "\n".join(
        [
            "2024-05-01T10:00:00Z ERROR HikariPool-1 - Connection is not available, request timed out after 30000ms.",
            "2024-05-01T10:00:01Z ERROR java.lang.OutOfMemoryError: Java heap space",
            "2024-05-01T10:00:02Z INFO all good",
            "2024-05-01T10:00:03Z ERROR dial tcp: lookup db on 10.0.0.1:53: no such host",
        ]
    )
    li = analyze_log("p", "c", text)
    assert li.lines == 4
    assert li.category_counts["db_pool"] == 1
    assert li.category_counts["timeout"] == 1
    assert li.category_counts["out_of_memory"] == 1
    assert li.category_counts["dns"] == 1
    assert "all good" not in str(li.samples)


def test_templates_cluster_variable_parts():
    assert template_of("2024-05-01T10:00:00Z order=123 took 45ms") == template_of(
        "2024-05-01T11:00:00Z order=9 took 7ms"
    )


def test_analyze_logs_keys():
    out = analyze_logs({"pod-a/app": "ERROR x", "pod-a/app#previous": "FATAL y"})
    assert {(i.pod, i.container, i.previous) for i in out} == {("pod-a", "app", False), ("pod-a", "app", True)}
