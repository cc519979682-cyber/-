"""Regression checks for Claude domain propagation and unrelated rule stability."""
import unittest
from build_personal_shadowrocket import CLAUDE_SUFFIXES, enforce_claude_priority


class ClaudePriorityTests(unittest.TestCase):
    def test_specific_subdomain_and_broad_direct_cannot_bypass_priority(self):
        source = ("[General]\nipv6 = false\n[Rule]\n"
                  "DOMAIN,api.anthropic.com,DIRECT\nIP-CIDR,0.0.0.0/0,DIRECT\n"
                  "DOMAIN-SUFFIX,claude.ai,DIRECT\nDOMAIN-SUFFIX,outlook.com,DIRECT\nFINAL,PROXY\n")
        result = enforce_claude_priority(source)
        rules = [line.split(',') for line in result.split('[Rule]\n')[1].splitlines() if not line.startswith('#')]
        for suffix in CLAUDE_SUFFIXES:
            for host in (suffix, 'api.' + suffix):
                matched = next(r for r in rules if r[0] == 'DOMAIN' and r[1] == host or r[0] == 'DOMAIN-SUFFIX' and (host == r[1] or host.endswith('.' + r[1])))
                self.assertEqual(matched[2:], ['PROXY', 'force-remote-dns'])
        self.assertEqual(enforce_claude_priority(result), result)

    def test_mail_general_and_other_rules_keep_content_and_order(self):
        prefix = '[General]\nupdate-url = https://example.invalid/original.conf\nipv6 = false\n'
        other = ['DOMAIN-SUFFIX,live.com,DIRECT', 'DOMAIN-SUFFIX,outlook.com,DIRECT',
                 'DOMAIN-SUFFIX,microsoft.com,DIRECT', 'IP-CIDR,100.64.0.0/10,DIRECT,no-resolve',
                 'DOMAIN-SUFFIX,notclaude.ai,DIRECT', 'FINAL,PROXY']
        result = enforce_claude_priority(prefix + '[Rule]\n' + '\n'.join(other) + '\n')
        self.assertTrue(result.startswith(prefix))
        remaining = [line for line in result.split('[Rule]\n')[1].splitlines() if line and not line.startswith('#') and not any(line.startswith('DOMAIN-SUFFIX,' + s + ',') for s in CLAUDE_SUFFIXES)]
        self.assertEqual(remaining, other)
        self.assertNotIn('[Proxy]', result)
        self.assertNotIn('[Proxy Group]', result)


if __name__ == '__main__':
    unittest.main()
