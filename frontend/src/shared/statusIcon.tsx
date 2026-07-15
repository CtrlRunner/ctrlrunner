import { BanIcon, CheckIcon, ClockIcon, CrossIcon, SkipIcon, WarnIcon } from './icons';
import { OUTCOME_LABELS } from './types';

export function StatusIcon({ outcome }: { outcome: string }) {
  const title = OUTCOME_LABELS[outcome] || outcome;
  const cls = `status-icon status-${outcome}`;
  switch (outcome) {
    case 'passed':
      return <CheckIcon className={cls} title={title} />;
    case 'failed':
      return <CrossIcon className={cls} title={title} />;
    case 'quarantined_failure':
      return <WarnIcon className={cls} title={title} />;
    case 'expected_failure':
      return <CheckIcon className={cls} title={title} />;
    case 'cancelled':
      return <BanIcon className={cls} title={title} />;
    case 'not_run':
      return <ClockIcon className={cls} title={title} />;
    default:
      return <SkipIcon className={cls} title={title} />;
  }
}
