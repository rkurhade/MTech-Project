#!/usr/bin/env python3
"""
Test script to run the expired secrets query for AAD-Test14
"""

import sys
import os
sys.path.append(os.path.dirname(os.path.abspath(__file__)))

from config import ConfigLoader
from services import DatabaseConfig, UserService

def test_expired_query():
    """Test the expired secrets query for AAD-Test14"""
    try:
        # Load database config
        db_config = DatabaseConfig(ConfigLoader.load_db_config())
        user_service = UserService(db_config)
        
        # Test the specific query
        query = """
        SELECT id, app_name, key_id, end_date, display_name, notified_expired, last_updated_at, user_info_id 
        FROM dbo.app_secrets 
        WHERE app_name = 'AAD-Test14' 
        AND end_date < GETDATE() 
        AND (notified_expired = 0 OR (notified_expired = 1 AND DATEDIFF(day, last_updated_at, GETDATE()) >= 2))
        """
        
        print("🔍 Testing expired secrets query for AAD-Test14...")
        print("Query:", query.strip())
        print("=" * 80)
        
        results = user_service._execute_query(query, fetch_type='dict_list')
        
        if results:
            print(f"✅ Found {len(results)} expired secret(s) for AAD-Test14:")
            for i, secret in enumerate(results, 1):
                print(f"\n📋 Secret #{i}:")
                print(f"  ID: {secret['id']}")
                print(f"  Key ID: {secret['key_id']}")
                print(f"  Display Name: {secret['display_name']}")
                print(f"  End Date: {secret['end_date']}")
                print(f"  Notified Expired: {secret['notified_expired']}")
                print(f"  Last Updated: {secret['last_updated_at']}")
                print(f"  User Info ID: {secret['user_info_id']}")
        else:
            print("❌ No expired secrets found for AAD-Test14 matching the criteria")
            
        # Also check all secrets for AAD-Test14
        print("\n" + "=" * 80)
        print("🔍 All secrets for AAD-Test14:")
        
        all_secrets_query = """
        SELECT id, app_name, key_id, end_date, display_name, notified_expired, last_updated_at, user_info_id,
               CASE 
                   WHEN end_date < GETDATE() THEN 'EXPIRED'
                   WHEN end_date BETWEEN GETDATE() AND DATEADD(day, 30, GETDATE()) THEN 'EXPIRING'
                   ELSE 'VALID'
               END as status,
               DATEDIFF(day, last_updated_at, GETDATE()) as days_since_update
        FROM dbo.app_secrets 
        WHERE app_name = 'AAD-Test14'
        ORDER BY end_date DESC
        """
        
        all_results = user_service._execute_query(all_secrets_query, fetch_type='dict_list')
        
        if all_results:
            for i, secret in enumerate(all_results, 1):
                print(f"\n📋 Secret #{i}:")
                print(f"  ID: {secret['id']}")
                print(f"  Key ID: {secret['key_id']}")
                print(f"  Display Name: {secret['display_name']}")
                print(f"  End Date: {secret['end_date']}")
                print(f"  Status: {secret['status']}")
                print(f"  Notified Expired: {secret['notified_expired']}")
                print(f"  Last Updated: {secret['last_updated_at']}")
                print(f"  Days Since Update: {secret['days_since_update']}")
        else:
            print("❌ No secrets found for AAD-Test14")
            
    except Exception as e:
        print(f"❌ Error testing query: {e}")
        import traceback
        traceback.print_exc()

if __name__ == "__main__":
    test_expired_query()