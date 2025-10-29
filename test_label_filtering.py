#!/usr/bin/env python3
"""Test label filtering functionality with pytest."""

import pytest
from content_resolver.config_manager import ConfigManager


def create_test_settings(labels_filter=None):
    """Create test settings for ConfigManager."""
    return {
        "configs": "test_configs",
        "output": "output",
        "use_cache": False,
        "dev_buildroot": True,
        "dnf_cache_dir_override": None,
        "parallel_max": 1,
        "selected_labels": labels_filter,
        "root_log_deps_cache_path": "cache_root_log_deps.json",
        "max_subprocesses": 10,
        "allowed_arches": ["aarch64", "ppc64le", "s390x", "x86_64"],
        "weird_packages_that_can_not_be_installed": ["glibc32"],
        "strict": False,
    }


@pytest.fixture(scope="module")
def all_configs():
    """Load all configs once for the test module."""
    settings = create_test_settings()
    config_manager = ConfigManager(settings)
    return config_manager.get_configs()


def test_load_all_configs_without_filter(all_configs):
    """Test loading all configs without filtering."""
    assert all_configs is not None
    assert len(all_configs['repos']) == 3
    assert len(all_configs['envs']) == 3
    assert len(all_configs['workloads']) == 8
    assert len(all_configs['views']) == 3
    # Labels are not loaded as separate entities in test_configs
    assert 'labels' in all_configs


def test_filter_single_label_reduces_configs(all_configs):
    """Test that filtering with a single label reduces config counts."""
    settings = create_test_settings(labels_filter="eln")
    config_manager = ConfigManager(settings)
    filtered_configs = config_manager.get_configs()

    # Verify filtering reduced counts
    assert len(filtered_configs['workloads']) <= len(all_configs['workloads'])
    assert len(filtered_configs['views']) <= len(all_configs['views'])
    assert len(filtered_configs['envs']) <= len(all_configs['envs'])
    assert len(filtered_configs['repos']) <= len(all_configs['repos'])


def test_filter_single_label_expected_counts(all_configs):
    """Test filtering with 'eln' label produces expected counts."""
    settings = create_test_settings(labels_filter="eln")
    config_manager = ConfigManager(settings)
    filtered_configs = config_manager.get_configs()

    # Verify specific expected results for 'eln' label
    assert len(filtered_configs['repos']) == 1
    assert len(filtered_configs['envs']) == 1
    assert len(filtered_configs['workloads']) == 5
    assert len(filtered_configs['views']) == 2


def test_filter_multiple_labels(all_configs):
    """Test filtering with multiple labels."""
    settings = create_test_settings(labels_filter="eln,eln-extras")
    config_manager = ConfigManager(settings)
    filtered_configs = config_manager.get_configs()

    # Verify we got configs matching our labels
    assert len(filtered_configs['workloads']) > 0 or len(filtered_configs['views']) > 0

    # Verify specific expected results
    assert len(filtered_configs['workloads']) == 7
    assert len(filtered_configs['envs']) == 2
    assert len(filtered_configs['views']) == 3


def test_filter_multiple_labels_includes_all_matching(all_configs):
    """Test that multiple labels are ORed, not ANDed."""
    settings_single = create_test_settings(labels_filter="eln")
    config_manager_single = ConfigManager(settings_single)
    eln_configs = config_manager_single.get_configs()

    settings_multi = create_test_settings(labels_filter="eln,eln-extras")
    config_manager_multi = ConfigManager(settings_multi)
    multi_configs = config_manager_multi.get_configs()

    # Multiple labels should include at least as many workloads as single label
    assert len(multi_configs['workloads']) >= len(eln_configs['workloads'])
    assert len(multi_configs['views']) >= len(eln_configs['views'])


@pytest.mark.parametrize("label", ["eln", "eln-extras", "fedora"])
def test_individual_labels(all_configs, label):
    """Test filtering with individual known labels."""
    settings = create_test_settings(labels_filter=label)
    config_manager = ConfigManager(settings)
    filtered_configs = config_manager.get_configs()

    # Should successfully filter without errors
    assert filtered_configs is not None
    assert isinstance(filtered_configs, dict)

    # Should not exceed original counts
    assert len(filtered_configs['workloads']) <= len(all_configs['workloads'])
    assert len(filtered_configs['views']) <= len(all_configs['views'])


def test_filter_nonexistent_label_does_not_crash():
    """Test that filtering with a non-existent label doesn't crash."""
    settings = create_test_settings(labels_filter="this-label-does-not-exist")
    config_manager = ConfigManager(settings)
    filtered_configs = config_manager.get_configs()

    # Should return empty or minimal configs, not crash
    assert filtered_configs is not None
    assert isinstance(filtered_configs, dict)


def test_filter_preserves_config_structure():
    """Test that filtering preserves the expected config structure."""
    settings = create_test_settings(labels_filter="eln")
    config_manager = ConfigManager(settings)
    filtered_configs = config_manager.get_configs()

    # Verify all expected top-level keys exist
    expected_keys = ['repos', 'envs', 'workloads', 'views', 'labels',
                     'unwanteds', 'buildroots', 'buildroot_pkg_relations']
    for key in expected_keys:
        assert key in filtered_configs, f"Missing expected key: {key}"
        assert isinstance(filtered_configs[key], dict), f"Key {key} should be a dict"


def test_filter_with_whitespace_in_labels():
    """Test that whitespace in label lists is handled correctly."""
    settings = create_test_settings(labels_filter=" eln , eln-extras ")
    config_manager = ConfigManager(settings)
    filtered_configs = config_manager.get_configs()

    # Should work the same as without whitespace
    assert filtered_configs is not None
    assert len(filtered_configs['workloads']) == 7
    assert len(filtered_configs['views']) == 3
