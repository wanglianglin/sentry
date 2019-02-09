import React from 'react';
import PropTypes from 'prop-types';

import Access from 'app/components/acl/access';
import AsyncView from 'app/views/asyncView';
import Field from 'app/views/settings/components/forms/field';
import Form from 'app/views/settings/components/forms/form';
import FormModel from 'app/views/settings/components/forms/model';
import SelectField from 'app/views/settings/components/forms/selectField';
import TextCopyInput from 'app/views/settings/components/forms/textCopyInput';
import TextField from 'app/views/settings/components/forms/textField';
import {Panel, PanelBody, PanelHeader} from 'app/components/panels';
import withOrganization from 'app/utils/withOrganization';
import SentryTypes from 'app/sentryTypes';
import {t, tct} from 'app/locale';

import MonitorHeader from './monitorHeader';

class MonitorModel extends FormModel {
  getTransformedData() {
    return Object.entries(this.fields.toJSON()).reduce((data, [k, v]) => {
      if (k.indexOf('config.') === 0) {
        if (!data.config) data.config = {};
        data.config[k.substr(7)] = v;
      }
      return data;
    }, {});
  }

  getTransformedValue(id) {
    if (id.indexOf('config') === 0) return this.getValue(id);
    return super.getTransformedValue(id);
  }
}

class EditMonitor extends AsyncView {
  static contextTypes = {
    organization: SentryTypes.Organization,
  };

  static propTypes = {
    location: PropTypes.object.isRequired,
    ...AsyncView.propTypes,
  };


  constructor(...args) {
    super(...args);
    this.form = new MonitorModel();
  }

  getEndpoints() {
    const {params, location} = this.props;
    return [
      [
        'monitor',
        `/monitors/${params.monitorId}/`,
        {
          query: location.query,
        },
      ],
    ];
  }

  formDataFromConfig(type, config) {
    switch (type) {
      case 'cron_job':
        return {
          'config.schedule_type': config.schedule_type,
          'config.schedule': config.schedule,
        }
      default:
        return {};
    }
  }

  onUpdate = (data) => {
    this.setState({
      monitor: {
        ...this.state.monitor,
        ...data,
      },
    });
  }

  onRequestSuccess({stateKey, data, jqXHR}) {
    if (stateKey === 'monitor') {
      this.form.setInitialData({
        name: data.name,
        type: data.type,
        ...this.formDataFromConfig(data.type, data.config)
      });
      this.setState({dataLoaded: true});
    }
  }

  getTitle() {
    if (this.state.monitor)
      return `${this.state.monitor.name} - Monitors - ${this.props.params.orgId}`;
    return `Monitors - ${this.props.params.orgId}`;
  }

  renderBody() {
    const {monitor} = this.state;
    if (!this.state.dataLoaded) return;
    return (
      <React.Fragment>
        <MonitorHeader monitor={monitor} orgId={this.props.params.orgId} onUpdate={this.onUpdate} />

        <Access access={['project:write']}>
          {({hasAccess}) => (
            <React.Fragment>
              <Form
                allowUndo
                requireChanges
                apiEndpoint={`/monitors/${monitor.id}/`}
                apiMethod="PUT"
                model={this.form}
                initialData={this.form.initialData}
                onFieldChange={this.handleFieldChange}
              >
                <Panel>
                  <PanelHeader>{t('Details')}</PanelHeader>

                  <PanelBody>
                    <Field label={t('ID')}>
                      <div className="controls">
                        <TextCopyInput>{monitor.id}</TextCopyInput>
                      </div>
                    </Field>
                    <TextField
                      name="name"
                      placeholder={t('My Cron Job')}
                      label={t('Name')}
                      disabled={!hasAccess}
                      required
                    />
                  </PanelBody>
                </Panel>
              <Panel>
                  <PanelHeader>{t('Config')}</PanelHeader>

                  <PanelBody>
                    <SelectField
                      name="type"
                      label={t('Type')}
                      disabled={!hasAccess}
                      choices={[['cron_job', 'Cron Job']]}
                      required
                    />
                    {this.form.getValue('type') === 'cron_job' &&
                      <SelectField
                        name="config.schedule_type"
                        label={t('Schedule Type')}
                        disabled={!hasAccess}
                        choices={[['crontab', 'Crontab']]}
                        required
                      />
                    }
                    {this.form.getValue('config.schedule_type') === 'crontab' &&
                      <TextField
                        name="config.schedule"
                        label={t('Schedule')}
                        disabled={!hasAccess}
                        placeholder="*/5 * * *"
                        required
                        help={tct('Changes to the schedule will apply on the next check-in. See [link:Wikipedia] for crontab syntax.', {
                          link: <a href="https://en.wikipedia.org/wiki/Cron"/>
                        })}
                      />
                    }
                  </PanelBody>
                </Panel>
              </Form>

            </React.Fragment>
          )}
        </Access>
      </React.Fragment>
    );
  }
}

export default withOrganization(EditMonitor);
