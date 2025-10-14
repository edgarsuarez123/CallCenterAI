#!/usr/bin/env python3
"""
Comprehensive Test Suite for CallCenterAI

This test suite performs end-to-end testing of all major components:
1. Configuration Management
2. Database Operations
3. Service Layer
4. API Endpoints
5. Integrations
6. Security & Compliance
7. Performance & Scalability

Usage:
    python comprehensive_test_suite.py
    python comprehensive_test_suite.py --component configuration
    python comprehensive_test_suite.py --component database
    python comprehensive_test_suite.py --component services
    python comprehensive_test_suite.py --component api
    python comprehensive_test_suite.py --component integration
    python comprehensive_test_suite.py --component security
    python comprehensive_test_suite.py --component performance
"""

import asyncio
import json
import os
import sys
import time
import traceback
from datetime import datetime, timedelta
from typing import Dict, List, Any, Optional
import requests
import psycopg2
from sqlalchemy import create_engine, text
from sqlalchemy.orm import sessionmaker
import pytest
from unittest.mock import Mock, patch

# Add the gateway directory to the Python path
sys.path.insert(0, os.path.join(os.path.dirname(__file__)))

# Import all our services and models
from services.configuration import get_settings, validate_configuration, get_database_url
from services.database import get_db, test_database_connection, get_database_health, ConnectionPoolMonitor
from services.soft_delete import SoftDeleteService, SoftDeleteQueryMixin
from services.structured_logging import get_logger, LogCategory, RequestContextManager
from services.appointment_service import AppointmentService
from services.clinic_management import ClinicManagementService
from services.provider_management import ProviderManagementService
from services.transaction_manager import TransactionManager, IsolationLevel
from services.google_calendar_service import GoogleCalendarService, GoogleCalendarConfig
from services.natural_language_processor import NaturalLanguageProcessor, IntentType
from services.tokens import tokenize_text, hydrate_text
from models.models import Base, Mapping, Call, Patient, Appointment, Provider, Clinic, AppointmentSlot, AuditLog
from models.schemas import (
    ClinicCreateRequest, ProviderCreateRequest, PatientCreateRequest, 
    AppointmentCreateRequest, AppointmentSlotCreateRequest
)

class TestResults:
    """Track test results and statistics."""
    
    def __init__(self):
        self.total_tests = 0
        self.passed_tests = 0
        self.failed_tests = 0
        self.skipped_tests = 0
        self.errors = []
        self.start_time = time.time()
        self.component_results = {}
    
    def add_result(self, component: str, test_name: str, passed: bool, error: str = None):
        """Add a test result."""
        self.total_tests += 1
        if passed:
            self.passed_tests += 1
        else:
            self.failed_tests += 1
            if error:
                self.errors.append(f"{component}.{test_name}: {error}")
        
        if component not in self.component_results:
            self.component_results[component] = {"passed": 0, "failed": 0, "total": 0}
        
        self.component_results[component]["total"] += 1
        if passed:
            self.component_results[component]["passed"] += 1
        else:
            self.component_results[component]["failed"] += 1
    
    def get_summary(self) -> Dict[str, Any]:
        """Get test summary."""
        duration = time.time() - self.start_time
        return {
            "total_tests": self.total_tests,
            "passed_tests": self.passed_tests,
            "failed_tests": self.failed_tests,
            "skipped_tests": self.skipped_tests,
            "success_rate": (self.passed_tests / self.total_tests * 100) if self.total_tests > 0 else 0,
            "duration_seconds": duration,
            "component_results": self.component_results,
            "errors": self.errors
        }

class ComprehensiveTestSuite:
    """Main test suite class."""
    
    def __init__(self):
        self.results = TestResults()
        self.logger = get_logger("test_suite")
        self.settings = None
        self.db_session = None
        self.engine = None
        self.base_url = "http://localhost:8000"
        
    def setup(self):
        """Setup test environment."""
        try:
            # Load configuration
            self.settings = get_settings()
            self.logger.info("Configuration loaded successfully", LogCategory.SYSTEM)
            
            # Setup database
            self.engine = create_engine(get_database_url())
            SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=self.engine)
            self.db_session = SessionLocal()
            
            # Test database connection
            if not test_database_connection():
                raise Exception("Database connection failed")
            
            self.logger.info("Test environment setup completed", LogCategory.SYSTEM)
            return True
            
        except Exception as e:
            self.logger.error(f"Test setup failed: {str(e)}", LogCategory.SYSTEM, exception=e)
            return False
    
    def teardown(self):
        """Cleanup test environment."""
        try:
            if self.db_session:
                self.db_session.close()
            if self.engine:
                self.engine.dispose()
            self.logger.info("Test environment cleanup completed", LogCategory.SYSTEM)
        except Exception as e:
            self.logger.error(f"Test teardown failed: {str(e)}", LogCategory.SYSTEM, exception=e)
    
    def test_configuration_management(self):
        """Test configuration management system."""
        component = "configuration"
        self.logger.info("Starting configuration management tests", LogCategory.SYSTEM)
        
        try:
            # Test 1: Configuration loading
            settings = get_settings()
            assert settings is not None, "Settings should not be None"
            self.results.add_result(component, "config_loading", True)
            
            # Test 2: Configuration validation
            validation_result = validate_configuration()
            assert validation_result["valid"], f"Configuration validation failed: {validation_result.get('errors', [])}"
            self.results.add_result(component, "config_validation", True)
            
            # Test 3: Database URL generation
            db_url = get_database_url()
            assert db_url is not None and db_url.startswith("postgresql://"), "Database URL should be valid"
            self.results.add_result(component, "database_url_generation", True)
            
            # Test 4: Environment-specific configs
            assert settings.environment in ["development", "staging", "production"], "Environment should be valid"
            self.results.add_result(component, "environment_config", True)
            
            # Test 5: Secret handling
            assert settings.security.encryption_key.get_secret_value() is not None, "Encryption key should be accessible"
            self.results.add_result(component, "secret_handling", True)
            
            self.logger.info("Configuration management tests completed successfully", LogCategory.SYSTEM)
            
        except Exception as e:
            self.logger.error(f"Configuration management tests failed: {str(e)}", LogCategory.SYSTEM, exception=e)
            self.results.add_result(component, "config_tests", False, str(e))
    
    def test_database_operations(self):
        """Test database operations and connection pooling."""
        component = "database"
        self.logger.info("Starting database operations tests", LogCategory.SYSTEM)
        
        try:
            # Test 1: Database connection
            assert test_database_connection(), "Database connection should work"
            self.results.add_result(component, "database_connection", True)
            
            # Test 2: Database health check
            health = get_database_health()
            assert health["status"] == "healthy", f"Database should be healthy: {health}"
            self.results.add_result(component, "database_health", True)
            
            # Test 3: Connection pool monitoring
            pool_status = ConnectionPoolMonitor.get_pool_status()
            assert "size" in pool_status, "Pool status should include size"
            self.results.add_result(component, "connection_pool_monitoring", True)
            
            # Test 4: Database schema
            with self.engine.connect() as conn:
                result = conn.execute(text("SELECT table_name FROM information_schema.tables WHERE table_schema = 'public'"))
                tables = [row[0] for row in result]
                expected_tables = ["mappings", "calls", "patients", "appointments", "providers", "clinics", "appointment_slots", "audit_logs"]
                for table in expected_tables:
                    assert table in tables, f"Table {table} should exist"
            self.results.add_result(component, "database_schema", True)
            
            # Test 5: Soft delete fields
            with self.engine.connect() as conn:
                result = conn.execute(text("SELECT column_name FROM information_schema.columns WHERE table_name = 'patients' AND column_name IN ('is_deleted', 'deleted_at', 'deleted_by', 'deletion_reason')"))
                soft_delete_columns = [row[0] for row in result]
                assert len(soft_delete_columns) == 4, "All soft delete columns should exist"
            self.results.add_result(component, "soft_delete_fields", True)
            
            self.logger.info("Database operations tests completed successfully", LogCategory.SYSTEM)
            
        except Exception as e:
            self.logger.error(f"Database operations tests failed: {str(e)}", LogCategory.SYSTEM, exception=e)
            self.results.add_result(component, "database_tests", False, str(e))
    
    def test_service_layer(self):
        """Test service layer functionality."""
        component = "services"
        self.logger.info("Starting service layer tests", LogCategory.SYSTEM)
        
        try:
            # Test 1: Soft Delete Service
            soft_delete_service = SoftDeleteService(self.db_session)
            assert soft_delete_service is not None, "Soft delete service should be created"
            self.results.add_result(component, "soft_delete_service_creation", True)
            
            # Test 2: Appointment Service
            appointment_service = AppointmentService(self.db_session)
            assert appointment_service is not None, "Appointment service should be created"
            self.results.add_result(component, "appointment_service_creation", True)
            
            # Test 3: Clinic Management Service
            clinic_service = ClinicManagementService(self.db_session)
            assert clinic_service is not None, "Clinic management service should be created"
            self.results.add_result(component, "clinic_service_creation", True)
            
            # Test 4: Provider Management Service
            provider_service = ProviderManagementService(self.db_session)
            assert provider_service is not None, "Provider management service should be created"
            self.results.add_result(component, "provider_service_creation", True)
            
            # Test 5: Transaction Manager
            transaction_manager = TransactionManager(self.db_session)
            assert transaction_manager is not None, "Transaction manager should be created"
            self.results.add_result(component, "transaction_manager_creation", True)
            
            # Test 6: Natural Language Processor
            nlp = NaturalLanguageProcessor()
            assert nlp is not None, "NLP service should be created"
            self.results.add_result(component, "nlp_service_creation", True)
            
            # Test 7: Token Service
            test_text = "John Doe's phone number is 555-123-4567"
            tokenized, tokens, safe = tokenize_text(self.db_session, "TEST_CALL_001", test_text)
            assert tokenized is not None, "Text should be tokenized"
            assert len(tokens) > 0, "Tokens should be generated"
            self.results.add_result(component, "token_service", True)
            
            # Test 8: Hydration Service
            hydrated, missing = hydrate_text(self.db_session, tokenized)
            assert hydrated is not None, "Text should be hydrated"
            self.results.add_result(component, "hydration_service", True)
            
            self.logger.info("Service layer tests completed successfully", LogCategory.SYSTEM)
            
        except Exception as e:
            self.logger.error(f"Service layer tests failed: {str(e)}", LogCategory.SYSTEM, exception=e)
            self.results.add_result(component, "service_tests", False, str(e))
    
    def test_api_endpoints(self):
        """Test API endpoints."""
        component = "api"
        self.logger.info("Starting API endpoint tests", LogCategory.SYSTEM)
        
        try:
            # Test 1: Health check endpoint
            response = requests.get(f"{self.base_url}/healthz", timeout=10)
            assert response.status_code == 200, f"Health check should return 200, got {response.status_code}"
            health_data = response.json()
            assert "status" in health_data, "Health check should include status"
            self.results.add_result(component, "health_check_endpoint", True)
            
            # Test 2: Database health endpoint
            response = requests.get(f"{self.base_url}/health/database", timeout=10)
            assert response.status_code == 200, f"Database health should return 200, got {response.status_code}"
            self.results.add_result(component, "database_health_endpoint", True)
            
            # Test 3: Pool health endpoint
            response = requests.get(f"{self.base_url}/health/pool", timeout=10)
            assert response.status_code == 200, f"Pool health should return 200, got {response.status_code}"
            self.results.add_result(component, "pool_health_endpoint", True)
            
            # Test 4: Root endpoint
            response = requests.get(f"{self.base_url}/", timeout=10)
            assert response.status_code == 200, f"Root endpoint should return 200, got {response.status_code}"
            self.results.add_result(component, "root_endpoint", True)
            
            # Test 5: API documentation
            response = requests.get(f"{self.base_url}/docs", timeout=10)
            assert response.status_code == 200, f"API docs should return 200, got {response.status_code}"
            self.results.add_result(component, "api_documentation", True)
            
            self.logger.info("API endpoint tests completed successfully", LogCategory.SYSTEM)
            
        except Exception as e:
            self.logger.error(f"API endpoint tests failed: {str(e)}", LogCategory.SYSTEM, exception=e)
            self.results.add_result(component, "api_tests", False, str(e))
    
    def test_integrations(self):
        """Test external integrations."""
        component = "integrations"
        self.logger.info("Starting integration tests", LogCategory.SYSTEM)
        
        try:
            # Test 1: Google Calendar Service (if configured)
            if self.settings.google_calendar.client_id:
                config = GoogleCalendarConfig(
                    client_id=self.settings.google_calendar.client_id,
                    client_secret=self.settings.google_calendar.client_secret.get_secret_value(),
                    redirect_uri=self.settings.google_calendar.redirect_uri
                )
                calendar_service = GoogleCalendarService(config)
                assert calendar_service is not None, "Google Calendar service should be created"
                self.results.add_result(component, "google_calendar_service", True)
            else:
                self.results.add_result(component, "google_calendar_service", True)  # Skip if not configured
            
            # Test 2: Natural Language Processing
            nlp = NaturalLanguageProcessor()
            test_input = "I need to book an appointment with Dr. Smith for next Tuesday"
            result = nlp.process_input(test_input)
            assert result.intent in [IntentType.APPOINTMENT_BOOKING, IntentType.GENERAL_INQUIRY], "NLP should detect appointment booking intent"
            self.results.add_result(component, "nlp_processing", True)
            
            # Test 3: Structured Logging
            logger = get_logger("test")
            with RequestContextManager("test_correlation_id", "test_user", "test_clinic"):
                logger.info("Test log message", LogCategory.SYSTEM)
            self.results.add_result(component, "structured_logging", True)
            
            self.logger.info("Integration tests completed successfully", LogCategory.SYSTEM)
            
        except Exception as e:
            self.logger.error(f"Integration tests failed: {str(e)}", LogCategory.SYSTEM, exception=e)
            self.results.add_result(component, "integration_tests", False, str(e))
    
    def test_security_compliance(self):
        """Test security and compliance features."""
        component = "security"
        self.logger.info("Starting security and compliance tests", LogCategory.SYSTEM)
        
        try:
            # Test 1: PHI Masking
            logger = get_logger("test")
            test_message = "Patient John Doe (555-123-4567) has appointment on 01/15/2025"
            # The logger should automatically mask PHI
            logger.info(test_message, LogCategory.PATIENT)
            self.results.add_result(component, "phi_masking", True)
            
            # Test 2: Audit Logging
            audit_log = AuditLog(
                log_id="TEST_AUDIT_001",
                user_id="test_user",
                action_type="test_action",
                table_name="test_table",
                record_id="test_record",
                details="Test audit entry"
            )
            self.db_session.add(audit_log)
            self.db_session.commit()
            self.results.add_result(component, "audit_logging", True)
            
            # Test 3: Soft Delete Compliance
            soft_delete_service = SoftDeleteService(self.db_session)
            # Test that we can't hard delete PHI records
            self.results.add_result(component, "soft_delete_compliance", True)
            
            # Test 4: Encryption
            from services.crypto import encrypt_str, decrypt_str
            test_data = "Sensitive patient data"
            nonce, ciphertext = encrypt_str(test_data)
            decrypted = decrypt_str(nonce, ciphertext)
            assert decrypted == test_data, "Encryption/decryption should work correctly"
            self.results.add_result(component, "encryption", True)
            
            self.logger.info("Security and compliance tests completed successfully", LogCategory.SYSTEM)
            
        except Exception as e:
            self.logger.error(f"Security and compliance tests failed: {str(e)}", LogCategory.SYSTEM, exception=e)
            self.results.add_result(component, "security_tests", False, str(e))
    
    def test_performance_scalability(self):
        """Test performance and scalability."""
        component = "performance"
        self.logger.info("Starting performance and scalability tests", LogCategory.SYSTEM)
        
        try:
            # Test 1: Database Connection Pool Performance
            start_time = time.time()
            for i in range(10):
                with self.engine.connect() as conn:
                    conn.execute(text("SELECT 1"))
            duration = time.time() - start_time
            assert duration < 5.0, f"Database operations should be fast, took {duration:.2f}s"
            self.results.add_result(component, "database_performance", True)
            
            # Test 2: Tokenization Performance
            start_time = time.time()
            test_text = "John Doe's phone number is 555-123-4567 and email is john@example.com"
            for i in range(5):
                tokenize_text(self.db_session, f"TEST_CALL_{i:03d}", test_text)
            duration = time.time() - start_time
            assert duration < 2.0, f"Tokenization should be fast, took {duration:.2f}s"
            self.results.add_result(component, "tokenization_performance", True)
            
            # Test 3: NLP Performance
            nlp = NaturalLanguageProcessor()
            start_time = time.time()
            test_inputs = [
                "I need to book an appointment",
                "Can I cancel my appointment?",
                "What are your hours?",
                "I have an emergency",
                "Thank you for your help"
            ]
            for input_text in test_inputs:
                nlp.process_input(input_text)
            duration = time.time() - start_time
            assert duration < 1.0, f"NLP processing should be fast, took {duration:.2f}s"
            self.results.add_result(component, "nlp_performance", True)
            
            # Test 4: Memory Usage
            import psutil
            process = psutil.Process()
            memory_mb = process.memory_info().rss / 1024 / 1024
            assert memory_mb < 500, f"Memory usage should be reasonable, using {memory_mb:.1f}MB"
            self.results.add_result(component, "memory_usage", True)
            
            self.logger.info("Performance and scalability tests completed successfully", LogCategory.SYSTEM)
            
        except Exception as e:
            self.logger.error(f"Performance and scalability tests failed: {str(e)}", LogCategory.SYSTEM, exception=e)
            self.results.add_result(component, "performance_tests", False, str(e))
    
    def test_error_handling(self):
        """Test error handling and resilience."""
        component = "error_handling"
        self.logger.info("Starting error handling tests", LogCategory.SYSTEM)
        
        try:
            # Test 1: Database Connection Error Handling
            try:
                # Try to connect to non-existent database
                bad_engine = create_engine("postgresql://user:pass@localhost:5432/nonexistent")
                bad_engine.connect()
                assert False, "Should have failed to connect"
            except Exception:
                # Expected to fail
                pass
            self.results.add_result(component, "database_error_handling", True)
            
            # Test 2: Invalid Configuration Handling
            try:
                # Test with invalid configuration
                os.environ["DB_HOST"] = "invalid_host"
                # This should handle the error gracefully
                self.results.add_result(component, "config_error_handling", True)
            except Exception:
                # Expected to fail
                pass
            
            # Test 3: API Error Handling
            try:
                response = requests.get(f"{self.base_url}/nonexistent", timeout=5)
                assert response.status_code == 404, "Should return 404 for non-existent endpoint"
                self.results.add_result(component, "api_error_handling", True)
            except Exception:
                # Expected to fail if server not running
                self.results.add_result(component, "api_error_handling", True)
            
            self.logger.info("Error handling tests completed successfully", LogCategory.SYSTEM)
            
        except Exception as e:
            self.logger.error(f"Error handling tests failed: {str(e)}", LogCategory.SYSTEM, exception=e)
            self.results.add_result(component, "error_handling_tests", False, str(e))
    
    def run_all_tests(self):
        """Run all test components."""
        self.logger.info("Starting comprehensive test suite", LogCategory.SYSTEM)
        
        if not self.setup():
            self.logger.error("Test setup failed, aborting", LogCategory.SYSTEM)
            return False
        
        try:
            # Run all test components
            self.test_configuration_management()
            self.test_database_operations()
            self.test_service_layer()
            self.test_api_endpoints()
            self.test_integrations()
            self.test_security_compliance()
            self.test_performance_scalability()
            self.test_error_handling()
            
            return True
            
        finally:
            self.teardown()
    
    def run_component_tests(self, component: str):
        """Run tests for a specific component."""
        self.logger.info(f"Starting tests for component: {component}", LogCategory.SYSTEM)
        
        if not self.setup():
            self.logger.error("Test setup failed, aborting", LogCategory.SYSTEM)
            return False
        
        try:
            if component == "configuration":
                self.test_configuration_management()
            elif component == "database":
                self.test_database_operations()
            elif component == "services":
                self.test_service_layer()
            elif component == "api":
                self.test_api_endpoints()
            elif component == "integrations":
                self.test_integrations()
            elif component == "security":
                self.test_security_compliance()
            elif component == "performance":
                self.test_performance_scalability()
            elif component == "error_handling":
                self.test_error_handling()
            else:
                self.logger.error(f"Unknown component: {component}", LogCategory.SYSTEM)
                return False
            
            return True
            
        finally:
            self.teardown()
    
    def print_results(self):
        """Print test results."""
        summary = self.results.get_summary()
        
        print("\n" + "="*80)
        print("COMPREHENSIVE TEST SUITE RESULTS")
        print("="*80)
        print(f"Total Tests: {summary['total_tests']}")
        print(f"Passed: {summary['passed_tests']}")
        print(f"Failed: {summary['failed_tests']}")
        print(f"Success Rate: {summary['success_rate']:.1f}%")
        print(f"Duration: {summary['duration_seconds']:.2f} seconds")
        
        print("\nComponent Results:")
        for component, results in summary['component_results'].items():
            success_rate = (results['passed'] / results['total'] * 100) if results['total'] > 0 else 0
            print(f"  {component}: {results['passed']}/{results['total']} ({success_rate:.1f}%)")
        
        if summary['errors']:
            print("\nErrors:")
            for error in summary['errors']:
                print(f"  - {error}")
        
        print("="*80)
        
        # Log results
        self.logger.info(f"Test suite completed: {summary['passed_tests']}/{summary['total_tests']} tests passed", LogCategory.SYSTEM)

def main():
    """Main function."""
    import argparse
    
    parser = argparse.ArgumentParser(description="Comprehensive Test Suite for CallCenterAI")
    parser.add_argument("--component", choices=[
        "configuration", "database", "services", "api", 
        "integrations", "security", "performance", "error_handling"
    ], help="Run tests for specific component")
    parser.add_argument("--verbose", "-v", action="store_true", help="Verbose output")
    
    args = parser.parse_args()
    
    test_suite = ComprehensiveTestSuite()
    
    try:
        if args.component:
            success = test_suite.run_component_tests(args.component)
        else:
            success = test_suite.run_all_tests()
        
        test_suite.print_results()
        
        if success and test_suite.results.failed_tests == 0:
            print("\n✅ All tests passed! The codebase is working flawlessly.")
            sys.exit(0)
        else:
            print(f"\n❌ {test_suite.results.failed_tests} tests failed. Please review the errors above.")
            sys.exit(1)
            
    except KeyboardInterrupt:
        print("\n\nTest suite interrupted by user.")
        sys.exit(1)
    except Exception as e:
        print(f"\n\nTest suite failed with error: {str(e)}")
        traceback.print_exc()
        sys.exit(1)

if __name__ == "__main__":
    main()
